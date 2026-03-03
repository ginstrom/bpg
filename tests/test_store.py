import time
import pytest
from pathlib import Path
import yaml
from bpg.models.schema import Process, ProcessMetadata, NodeInstance, NodeType, TypeDef
from bpg.state.store import StateStore
from bpg.compiler.ir import compile_process
from bpg.compiler.validator import validate_process

def _save(store, process, deployments=None):
    p = process
    if not p.types:
        p = p.model_copy(update={"types": {"_RequiredType": TypeDef(root={"ok": "bool"})}})
    validate_process(p)
    ir = compile_process(p)
    return store.save_process(ir, deployments=deployments)

def test_store_save_load(tmp_path: Path):
    store = StateStore(tmp_path)
    process = Process(
        metadata=ProcessMetadata(name="test-proc", version="1.0"),
        node_types={"t1@v1": NodeType(**{"in": "object", "out": "object", "provider": "p", "version": "v1"})},
        nodes={"n1": NodeInstance(type="t1@v1")},
        edges=[],
        trigger="n1"
    )
    
    h = _save(store, process)
    assert len(h) == 64
    
    loaded = store.load_process("test-proc")
    assert loaded is not None
    assert loaded.metadata.name == "test-proc"
    assert loaded.nodes["n1"].node_type == "t1@v1"

def test_store_load_missing(tmp_path: Path):
    store = StateStore(tmp_path)
    assert store.load_process("nope") is None


def test_store_load_process_backfills_legacy_node_type_version(tmp_path: Path):
    store = StateStore(tmp_path)
    processes_dir = tmp_path / "processes"
    processes_dir.mkdir(parents=True, exist_ok=True)

    legacy_record = {
        "hash": "dummy",
        "version": 1,
        "definition": {
            "metadata": {"name": "legacy-proc", "version": "1.0.0"},
            "types": {"T": {"value": "string"}},
            "node_types": {
                "legacy_node@v1": {
                    "in": "T",
                    "out": "T",
                    "provider": "mock",
                    "config_schema": {},
                }
            },
            "nodes": {"n1": {"type": "legacy_node@v1", "config": {}}},
            "trigger": "n1",
            "edges": [],
        },
    }
    (processes_dir / "legacy-proc.yaml").write_text(yaml.safe_dump(legacy_record, sort_keys=False))

    loaded = store.load_process("legacy-proc")
    assert loaded is not None
    assert loaded.node_types["legacy_node@v1"].version == "v1"


def test_store_version_increments(tmp_path: Path):
    """Applying twice bumps the version from 1 to 2."""
    store = StateStore(tmp_path)
    process = Process(
        metadata=ProcessMetadata(name="ver-proc", version="1.0"),
        node_types={"t1@v1": NodeType(**{"in": "object", "out": "object", "provider": "p", "version": "v1"})},
        nodes={"n1": NodeInstance(type="t1@v1")},
        edges=[],
        trigger="n1"
    )
    _save(store, process)
    record1 = store.load_record("ver-proc")
    assert record1["version"] == 1
    assert "applied_at" in record1

    _save(store, process)
    record2 = store.load_record("ver-proc")
    assert record2["version"] == 2


def test_store_deployments_persisted(tmp_path: Path):
    """Deployment metadata is round-tripped through load_record."""
    store = StateStore(tmp_path)
    process = Process(
        metadata=ProcessMetadata(name="dep-proc", version="1.0"),
        node_types={"webhook@v1": NodeType(**{"in": "object", "out": "object", "provider": "p", "version": "v1"})},
        nodes={"wh": NodeInstance(type="webhook@v1")},
        edges=[],
        trigger="wh"
    )
    deployments = {"wh": {"provider_id": "http.webhook", "artifacts": {"url": "https://example.com/hook"}}}
    _save(store, process, deployments=deployments)
    record = store.load_record("dep-proc")
    assert record["deployments"]["wh"]["artifacts"]["url"] == "https://example.com/hook"
    assert "artifact_checksum" in record["deployments"]["wh"]
    assert store.verify_artifact_checksums("dep-proc") is True


def test_store_persists_explicit_pins_and_checksums(tmp_path: Path):
    store = StateStore(tmp_path)
    process = Process(
        metadata=ProcessMetadata(name="pins-proc", version="2.1.0"),
        types={"MyType": TypeDef(root={"ok": "bool"})},
        node_types={"t1@v1": NodeType(**{"in": "MyType", "out": "MyType", "provider": "p", "version": "v1"})},
        nodes={"n1": NodeInstance(type="t1@v1")},
        edges=[],
        trigger="n1",
    )
    _save(store, process)
    record = store.load_record("pins-proc")
    assert record["process_version"] == "2.1.0"
    assert record["node_type_pins"] == {"n1": "t1@v1"}
    assert record["type_pins"] == ["MyType"]
    assert "MyType" in record["type_checksums"]
    assert "t1@v1" in record["node_type_checksums"]
    assert isinstance(record["ir_checksum"], str) and len(record["ir_checksum"]) == 64


def test_verify_artifact_checksums_detects_drift(tmp_path: Path):
    from bpg.state.store import StateStoreError

    store = StateStore(tmp_path)
    process = Process(
        metadata=ProcessMetadata(name="drift-proc", version="1.0"),
        node_types={"webhook@v1": NodeType(**{"in": "object", "out": "object", "provider": "p", "version": "v1"})},
        nodes={"wh": NodeInstance(type="webhook@v1")},
        edges=[],
        trigger="wh"
    )
    deployments = {"wh": {"provider_id": "http.webhook", "artifacts": {"url": "https://example.com/hook"}}}
    _save(store, process, deployments=deployments)

    record = store.load_record("drift-proc")
    record["deployments"]["wh"]["artifacts"]["url"] = "https://evil.example.com/hook"
    process_file = tmp_path / "processes" / "drift-proc.yaml"
    import yaml
    process_file.write_text(yaml.safe_dump(record, sort_keys=False))

    with pytest.raises(StateStoreError, match="Artifact checksum mismatch"):
        store.verify_artifact_checksums("drift-proc")


def test_create_and_load_run(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run(
        "run-1",
        "my-process",
        {"key": "val"},
        process_snapshot={"process_hash": "abc", "process_record_version": 3, "process_version": "1.2.0"},
    )
    record = store.load_run("run-1")
    assert record is not None
    assert record["run_id"] == "run-1"
    assert record["process_name"] == "my-process"
    assert record["status"] == "running"
    assert record["input"] == {"key": "val"}
    assert record["process_hash"] == "abc"
    assert record["process_record_version"] == 3
    assert record["process_version"] == "1.2.0"
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


def test_save_node_record_merges_with_existing_snapshot(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run("run-merge", "p", {})
    store.save_node_record("run-merge", "triage", {"node": "triage", "status": "running"})
    store.save_node_record("run-merge", "triage", {"status": "completed", "output": {"risk": "low"}})
    loaded = store.load_node_record("run-merge", "triage")
    assert loaded is not None
    assert loaded["node"] == "triage"
    assert loaded["status"] == "completed"
    assert loaded["output"]["risk"] == "low"


def test_execution_log_is_append_only(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run("run-log", "p", {})
    store.append_execution_event("run-log", {"node": "a", "status": "completed"})
    store.append_execution_event("run-log", {"node": "b", "status": "failed"})
    events = store.load_execution_log("run-log")
    assert [e["node"] for e in events] == ["a", "b"]


def test_load_node_record_missing(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run("run-nm", "p", {})
    assert store.load_node_record("run-nm", "ghost_node") is None


def test_save_node_record_no_run_raises(tmp_path: Path):
    from bpg.state.store import StateStoreError
    store = StateStore(tmp_path)
    with pytest.raises(StateStoreError, match="does not exist"):
        store.save_node_record("nonexistent-run", "node", {})


def test_apply_audit_policy_exports_run_log(tmp_path: Path):
    store = StateStore(tmp_path)
    store.create_run("r-export", "proc-a", {})
    store.update_run("r-export", {"status": "completed"})
    store.apply_audit_policy(
        run_id="r-export",
        process_name="proc-a",
        audit_record={"retention": "365d", "export_to": "splunk.audit"},
        run_status="completed",
        execution_log=[{"node": "n1", "status": "completed"}],
    )
    export_file = tmp_path / "exports" / "splunk.audit.jsonl"
    assert export_file.exists()
    lines = export_file.read_text().strip().splitlines()
    assert len(lines) == 1
    assert "\"run_id\": \"r-export\"" in lines[0]


def test_apply_audit_policy_retention_prunes_old_runs(tmp_path: Path):
    import yaml

    store = StateStore(tmp_path)
    store.create_run("r-old", "proc-a", {})
    old_path = tmp_path / "runs" / "r-old" / "run.yaml"
    old_record = yaml.safe_load(old_path.read_text())
    old_record["started_at"] = "2000-01-01T00:00:00+00:00"
    old_path.write_text(yaml.safe_dump(old_record, sort_keys=False))

    store.create_run("r-new", "proc-a", {})
    store.apply_audit_policy(
        run_id="r-new",
        process_name="proc-a",
        audit_record={"retention": "1d"},
        run_status="completed",
        execution_log=[],
    )
    assert store.load_run("r-old") is None
    assert store.load_run("r-new") is not None


def test_prune_runs_dry_run_does_not_delete(tmp_path: Path):
    import yaml

    store = StateStore(tmp_path)
    store.create_run("r-old", "proc-a", {})
    old_path = tmp_path / "runs" / "r-old" / "run.yaml"
    old_record = yaml.safe_load(old_path.read_text())
    old_record["started_at"] = "2000-01-01T00:00:00+00:00"
    old_path.write_text(yaml.safe_dump(old_record, sort_keys=False))

    matched = store.prune_runs(process_name="proc-a", older_than="1d", dry_run=True)
    assert matched == ["r-old"]
    assert store.load_run("r-old") is not None


def test_prune_runs_filters_by_status_and_deletes(tmp_path: Path):
    import yaml

    store = StateStore(tmp_path)
    store.create_run("r-failed", "proc-a", {})
    store.update_run("r-failed", {"status": "failed"})
    store.create_run("r-completed", "proc-a", {})
    store.update_run("r-completed", {"status": "completed"})

    for rid in ("r-failed", "r-completed"):
        path = tmp_path / "runs" / rid / "run.yaml"
        rec = yaml.safe_load(path.read_text())
        rec["started_at"] = "2000-01-01T00:00:00+00:00"
        path.write_text(yaml.safe_dump(rec, sort_keys=False))

    matched = store.prune_runs(
        process_name="proc-a",
        older_than="1d",
        statuses={"failed"},
    )
    assert matched == ["r-failed"]
    assert store.load_run("r-failed") is None
    assert store.load_run("r-completed") is not None
