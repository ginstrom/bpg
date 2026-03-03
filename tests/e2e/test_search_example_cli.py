from __future__ import annotations

import os
import re
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app
from bpg.state.store import StateStore


runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]
INGEST_FILE = REPO_ROOT / "examples" / "search" / "ingest.bpg.yaml"
RETRIEVE_FILE = REPO_ROOT / "examples" / "search" / "retrieve.bpg.yaml"


def test_e2e_cli_search_examples_ingest_then_retrieve(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "guide.md").write_text(
        "# API Guide\n\nBPG uses typed process graphs for orchestration.\n",
        encoding="utf-8",
    )

    state_dir = tmp_path / "state"
    search_store_dir = tmp_path / "search-store"
    search_store_dir.mkdir(parents=True, exist_ok=True)

    original_search_store = os.environ.get("BPG_SEARCH_STORE_DIR")
    os.environ["BPG_SEARCH_STORE_DIR"] = str(search_store_dir)
    try:
        ingest_apply = runner.invoke(
            app,
            ["apply", str(INGEST_FILE), "--state-dir", str(state_dir), "--auto-approve"],
        )
        assert ingest_apply.exit_code == 0

        retrieve_apply = runner.invoke(
            app,
            ["apply", str(RETRIEVE_FILE), "--state-dir", str(state_dir), "--auto-approve"],
        )
        assert retrieve_apply.exit_code == 0

        ingest_input = tmp_path / "ingest-input.yaml"
        ingest_input.write_text(
            f"root_dir: {docs_dir}\nglob: '*.md'\n",
            encoding="utf-8",
        )
        ingest_run = runner.invoke(
            app,
            ["run", "search-ingest", "--input", str(ingest_input), "--state-dir", str(state_dir)],
        )
        assert ingest_run.exit_code == 0
        ingest_match = re.search(r"Run\s+([0-9a-f-]{36})\s+status=", ingest_run.stdout)
        assert ingest_match is not None

        # Current baseline writes Weaviate records to a local JSONL store.
        store_file = search_store_dir / "search_main.jsonl"
        assert store_file.exists()
        assert store_file.read_text(encoding="utf-8").strip()

        retrieve_input = tmp_path / "retrieve-input.yaml"
        retrieve_input.write_text("query: typed process graph\n", encoding="utf-8")
        retrieve_run = runner.invoke(
            app,
            ["run", "search-retrieve", "--input", str(retrieve_input), "--state-dir", str(state_dir)],
        )
        assert retrieve_run.exit_code == 0
        retrieve_match = re.search(r"Run\s+([0-9a-f-]{36})\s+status=", retrieve_run.stdout)
        assert retrieve_match is not None
        retrieve_run_id = retrieve_match.group(1)
    finally:
        if original_search_store is None:
            os.environ.pop("BPG_SEARCH_STORE_DIR", None)
        else:
            os.environ["BPG_SEARCH_STORE_DIR"] = original_search_store

    state_store = StateStore(state_dir)
    retrieve_record = state_store.load_run(retrieve_run_id)
    assert retrieve_record is not None
    assert retrieve_record["status"] == "completed"

    search_node = state_store.load_node_record(retrieve_run_id, "search")
    assert search_node is not None
    hits = (search_node.get("output") or {}).get("hits") or []
    assert len(hits) >= 1
    assert "typed process graphs" in hits[0]["text"].lower()
