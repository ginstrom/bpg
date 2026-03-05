from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bpg.cli import app
from bpg.state.store import StateStore


runner = CliRunner()
REPO_ROOT = Path(__file__).resolve().parents[2]
INGEST_FILE = REPO_ROOT / "examples" / "search" / "ingest.bpg.yaml"
RETRIEVE_FILE = REPO_ROOT / "examples" / "search" / "retrieve.bpg.yaml"
SEARCH_RESOURCES_FILE = REPO_ROOT / "examples" / "search" / "search-resources.bpg.yaml"


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def _run_compose(compose_dir: Path, *args: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose"] + list(args)
    result = subprocess.run(
        cmd,
        cwd=compose_dir,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        stderr_lower = (result.stderr or "").lower()
        if "port is already allocated" in stderr_lower or "address already in use" in stderr_lower:
            pytest.fail(
                "docker compose failed because required host ports are already in use. "
                "Please bring down your existing local system stack and rerun this test.\n"
                f"cwd={compose_dir}\n"
                f"cmd={' '.join(cmd)}\n"
                f"stderr:\n{result.stderr}"
            )
        pytest.fail(
            "docker compose command failed\n"
            f"cwd={compose_dir}\n"
            f"cmd={' '.join(cmd)}\n"
            f"exit={result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )
    return result


def test_e2e_packaged_search_examples_via_docker_compose(tmp_path: Path) -> None:
    if not _docker_ready():
        pytest.skip("Docker is not available for packaged compose search e2e test")

    ingest_pkg = tmp_path / "pkg-ingest"
    retrieve_pkg = tmp_path / "pkg-retrieve"

    ingest_package = runner.invoke(
        app,
        ["package", str(INGEST_FILE), "--output-dir", str(ingest_pkg), "--force"],
    )
    assert ingest_package.exit_code == 0, ingest_package.stdout

    retrieve_package = runner.invoke(
        app,
        ["package", str(RETRIEVE_FILE), "--output-dir", str(retrieve_pkg), "--force"],
    )
    assert retrieve_package.exit_code == 0, retrieve_package.stdout

    unique_phrase = "search-e2e-synthetic-typed-graph-token"
    ingest_state_dir = ingest_pkg / "state"
    docs_dir = ingest_state_dir / "docs"
    docs_dir.mkdir(parents=True, exist_ok=True)
    (docs_dir / "guide.md").write_text(
        "# Guide\n\nThis document contains search-e2e-synthetic-typed-graph-token for validation.\n",
        encoding="utf-8",
    )
    (ingest_state_dir / "ingest-input.yaml").write_text(
        "root_dir: /app/.bpg-state/docs\nglob: '*.md'\n",
        encoding="utf-8",
    )

    ingest_store_file = ingest_state_dir / "search" / "search_main.jsonl"

    try:
        _run_compose(ingest_pkg, "up", "--build", "-d")
        _run_compose(
            ingest_pkg,
            "--profile",
            "runner",
            "run",
            "--rm",
            "-v",
            f"{SEARCH_RESOURCES_FILE}:/app/search-resources.bpg.yaml:ro",
            "bpg",
            "apply",
            "/app/process.bpg.yaml",
            "--state-dir",
            "/app/.bpg-state",
            "--auto-approve",
        )
        ingest_run = _run_compose(
            ingest_pkg,
            "--profile",
            "runner",
            "run",
            "--rm",
            "bpg",
            "run",
            "search-ingest",
            "--input",
            "/app/.bpg-state/ingest-input.yaml",
            "--state-dir",
            "/app/.bpg-state",
        )

        ingest_match = re.search(r"Run\s+([0-9a-f-]{36})\s+status=", ingest_run.stdout)
        assert ingest_match is not None
        assert ingest_store_file.exists()
        assert unique_phrase in ingest_store_file.read_text(encoding="utf-8").lower()

        retrieve_state_dir = retrieve_pkg / "state"
        retrieve_store_dir = retrieve_state_dir / "search"
        retrieve_store_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ingest_store_file, retrieve_store_dir / "search_main.jsonl")
        (retrieve_state_dir / "retrieve-input.yaml").write_text(
            "query: synthetic typed graph token\n",
            encoding="utf-8",
        )
        _run_compose(ingest_pkg, "down", "--volumes")

        _run_compose(retrieve_pkg, "up", "--build", "-d")
        _run_compose(
            retrieve_pkg,
            "--profile",
            "runner",
            "run",
            "--rm",
            "-v",
            f"{SEARCH_RESOURCES_FILE}:/app/search-resources.bpg.yaml:ro",
            "bpg",
            "apply",
            "/app/process.bpg.yaml",
            "--state-dir",
            "/app/.bpg-state",
            "--auto-approve",
        )
        retrieve_run = _run_compose(
            retrieve_pkg,
            "--profile",
            "runner",
            "run",
            "--rm",
            "bpg",
            "run",
            "search-retrieve",
            "--input",
            "/app/.bpg-state/retrieve-input.yaml",
            "--state-dir",
            "/app/.bpg-state",
        )

        retrieve_match = re.search(r"Run\s+([0-9a-f-]{36})\s+status=", retrieve_run.stdout)
        assert retrieve_match is not None
        retrieve_run_id = retrieve_match.group(1)

        state_store = StateStore(retrieve_state_dir)
        search_node = state_store.load_node_record(retrieve_run_id, "search")
        assert search_node is not None
        hits = (search_node.get("output") or {}).get("hits") or []
        assert len(hits) >= 1
        assert unique_phrase in hits[0]["text"].lower()
    finally:
        if ingest_pkg.exists():
            subprocess.run(
                ["docker", "compose", "down", "--volumes"],
                cwd=ingest_pkg,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
        if retrieve_pkg.exists():
            subprocess.run(
                ["docker", "compose", "down", "--volumes"],
                cwd=retrieve_pkg,
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
