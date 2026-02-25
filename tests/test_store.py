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
