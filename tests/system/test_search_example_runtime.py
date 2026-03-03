from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.runtime.engine import Engine
from bpg.state.store import StateStore


REPO_ROOT = Path(__file__).resolve().parents[2]
INGEST_FILE = REPO_ROOT / "examples" / "search" / "ingest.bpg.yaml"
RETRIEVE_FILE = REPO_ROOT / "examples" / "search" / "retrieve.bpg.yaml"


def test_search_examples_ingest_then_retrieve(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "guide.md").write_text(
        "# API Guide\n\nBPG uses typed process graphs for orchestration.\n",
        encoding="utf-8",
    )

    store_dir = tmp_path / "state"
    search_store_dir = tmp_path / "search-store"
    search_store_dir.mkdir(parents=True, exist_ok=True)
    store = StateStore(store_dir)

    ingest = parse_process_file(INGEST_FILE)
    validate_process(ingest)
    retrieve = parse_process_file(RETRIEVE_FILE)
    validate_process(retrieve)

    with patch.dict("os.environ", {"BPG_SEARCH_STORE_DIR": str(search_store_dir)}, clear=False):
        ingest_run_id = Engine(process=ingest, state_store=store).trigger(
            {"root_dir": str(docs_dir), "glob": "*.md"}
        )
        ingest_run = store.load_run(ingest_run_id)
        assert ingest_run is not None
        assert ingest_run["status"] == "completed"

        retrieve_run_id = Engine(process=retrieve, state_store=store).trigger({"query": "typed process graph"})
        retrieve_run = store.load_run(retrieve_run_id)
        assert retrieve_run is not None
        assert retrieve_run["status"] == "completed"

    search_node = store.load_node_record(retrieve_run_id, "search")
    assert search_node is not None
    hits = (search_node.get("output") or {}).get("hits") or []
    assert len(hits) >= 1
    assert "typed process graphs" in hits[0]["text"].lower()
