import time
import pytest
from pathlib import Path
from bpg.models.schema import Process, ProcessMetadata, NodeInstance
from bpg.state.store import StateStore

def test_store_save_load(tmp_path: Path):
    store = StateStore(tmp_path)
    process = Process(
        metadata=ProcessMetadata(name="test-proc", version="1.0"),
        nodes={"n1": NodeInstance(type="t1@v1")},
        edges=[],
        trigger="n1"
    )
    
    h = store.save_process(process)
    assert len(h) == 64
    
    loaded = store.load_process("test-proc")
    assert loaded is not None
    assert loaded.metadata.name == "test-proc"
    assert loaded.nodes["n1"].node_type == "t1@v1"

def test_store_load_missing(tmp_path: Path):
    store = StateStore(tmp_path)
    assert store.load_process("nope") is None


def test_store_version_increments(tmp_path: Path):
    """Applying twice bumps the version from 1 to 2."""
    store = StateStore(tmp_path)
    process = Process(
        metadata=ProcessMetadata(name="ver-proc", version="1.0"),
        nodes={"n1": NodeInstance(type="t1@v1")},
        edges=[],
        trigger="n1"
    )
    store.save_process(process)
    record1 = store.load_record("ver-proc")
    assert record1["version"] == 1
    assert "applied_at" in record1

    store.save_process(process)
    record2 = store.load_record("ver-proc")
    assert record2["version"] == 2


def test_store_deployments_persisted(tmp_path: Path):
    """Deployment metadata is round-tripped through load_record."""
    store = StateStore(tmp_path)
    process = Process(
        metadata=ProcessMetadata(name="dep-proc", version="1.0"),
        nodes={"wh": NodeInstance(type="webhook@v1")},
        edges=[],
        trigger="wh"
    )
    deployments = {"wh": {"provider_id": "http.webhook", "artifacts": {"url": "https://example.com/hook"}}}
    store.save_process(process, deployments=deployments)
    record = store.load_record("dep-proc")
    assert record["deployments"]["wh"]["artifacts"]["url"] == "https://example.com/hook"


def test_create_and_load_run(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run("run-1", "my-process", {"key": "val"})
    record = store.load_run("run-1")
    assert record is not None
    assert record["run_id"] == "run-1"
    assert record["process_name"] == "my-process"
    assert record["status"] == "running"
    assert record["input"] == {"key": "val"}
    assert "started_at" in record


def test_create_run_duplicate_raises(tmp_path: Path):
    from bpg.state.store import StateStoreError
    store = StateStore(tmp_path)
    store.create_run("run-dup", "p", {})
    with pytest.raises(StateStoreError, match="already exists"):
        store.create_run("run-dup", "p", {})


def test_load_run_missing(tmp_path: Path):
    store = StateStore(tmp_path)
    assert store.load_run("nonexistent") is None


def test_update_run(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run("run-upd", "p", {})
    store.update_run("run-upd", {"status": "completed", "completed_at": "2026-01-01T00:00:00+00:00"})
    record = store.load_run("run-upd")
    assert record["status"] == "completed"
    assert "completed_at" in record


def test_update_run_missing_raises(tmp_path: Path):
    from bpg.state.store import StateStoreError
    store = StateStore(tmp_path)
    with pytest.raises(StateStoreError, match="not found"):
        store.update_run("ghost-run", {"status": "failed"})


def test_list_runs_empty(tmp_path: Path):
    store = StateStore(tmp_path)
    assert store.list_runs() == []


def test_list_runs_returns_all(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run("r1", "proc-a", {})
    time.sleep(0.01)
    store.create_run("r2", "proc-b", {})
    runs = store.list_runs()
    assert len(runs) == 2
    # sorted descending by started_at — r2 is more recent
    assert runs[0]["run_id"] == "r2"


def test_list_runs_filtered_by_process(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run("r1", "proc-a", {})
    store.create_run("r2", "proc-b", {})
    runs = store.list_runs(process_name="proc-a")
    assert len(runs) == 1
    assert runs[0]["run_id"] == "r1"


def test_save_and_load_node_record(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run("run-n1", "p", {})
    record = {"node": "triage", "status": "completed", "output": {"risk": "low"}}
    store.save_node_record("run-n1", "triage", record)
    loaded = store.load_node_record("run-n1", "triage")
    assert loaded is not None
    assert loaded["status"] == "completed"
    assert loaded["output"]["risk"] == "low"


def test_load_node_record_missing(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run("run-nm", "p", {})
    assert store.load_node_record("run-nm", "ghost_node") is None


def test_save_node_record_no_run_raises(tmp_path: Path):
    from bpg.state.store import StateStoreError
    store = StateStore(tmp_path)
    with pytest.raises(StateStoreError, match="does not exist"):
        store.save_node_record("nonexistent-run", "node", {})
