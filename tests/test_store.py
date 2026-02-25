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
