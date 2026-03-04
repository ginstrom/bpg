from pathlib import Path

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.providers import PROVIDER_REGISTRY
from bpg.providers.mock import MockProvider
from bpg.runtime.engine import Engine
from bpg.state.store import StateStore


def _process(tmp_path: Path):
    path = tmp_path / "process.bpg.yaml"
    path.write_text(
        """
types:
  Out:
    ok: bool
node_types:
  start_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  work_node@v1:
    in: object
    out: Out
    provider: mock
    version: v1
    config_schema: {}
nodes:
  start:
    type: start_node@v1
    config: {}
  work:
    type: work_node@v1
    config: {}
trigger: start
output: work.out.ok
edges:
  - from: start
    to: work
"""
    )
    process = parse_process_file(path)
    validate_process(process)
    return process


def _artifact_process(tmp_path: Path):
    path = tmp_path / "artifact-process.bpg.yaml"
    path.write_text(
        """
types:
  In:
    row_ids: list<number>
  Row:
    row_id: number
    review: string
    source_sentiment: string
  Batch:
    rows: list<Row>
  Out:
    items: list<object>
node_types:
  ingest@v1:
    in: In
    out: In
    provider: core.passthrough
    version: v1
    config_schema: {}
  select@v1:
    in: In
    out: Batch
    provider: core.dataset.select_rows
    version: v1
    config_schema:
      rows: list<object>
  enrich@v1:
    in: Batch
    out: Out
    provider: mock
    version: v1
    config_schema: {}
nodes:
  ingest:
    type: ingest@v1
    config: {}
  select:
    type: select@v1
    config:
      rows:
        - row_id: 1
          review: one
          source_sentiment: positive
        - row_id: 2
          review: two
          source_sentiment: negative
  enrich:
    type: enrich@v1
    config: {}
trigger: ingest
edges:
  - from: ingest
    to: select
    with:
      row_ids: ingest.out.row_ids
  - from: select
    to: enrich
    with:
      rows: select.out.rows
output: enrich.out
artifacts:
  - name: enriched_items
    from: enrich.out.items
    format: jsonl
  - name: run_output
    from: output
    format: json
"""
    )
    process = parse_process_file(path)
    validate_process(process)
    return process


def test_engine_step_executes_existing_running_run(tmp_path: Path):
    process = _process(tmp_path)
    store = StateStore(tmp_path / "state")
    store.save_process(compile_process(process))
    deployed = store.load_record("default")
    run_id = "resume-run-1"
    store.create_run(
        run_id,
        "default",
        {},
        process_snapshot={
            "process_hash": deployed["hash"],
            "process_record_version": deployed["version"],
            "process_version": deployed.get("process_version"),
        },
    )

    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    try:
        engine = Engine(process=process, state_store=store)
        engine.step(run_id)
        run = store.load_run(run_id)
        assert run is not None
        assert run["status"] == "completed"
        assert run["output"] is True
        assert run["process_hash"] is not None
        assert run["process_record_version"] == 1
        events = store.load_execution_log(run_id)
        assert len(events) == 4
        event_types = [e["event_type"] for e in events]
        assert event_types[0] == "run_started"
        assert event_types[-1] == "run_completed"
        assert {e["node"] for e in events if "node" in e} == {"start", "work"}
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock


def test_engine_materializes_declared_artifacts(tmp_path: Path):
    process = _artifact_process(tmp_path)
    store = StateStore(tmp_path / "state")
    store.save_process(compile_process(process))

    mock = MockProvider()
    mock.set_default({"items": [{"row_id": 1, "summary": "ok"}]})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    try:
        engine = Engine(process=process, state_store=store)
        run_id = engine.trigger(input_payload={"row_ids": [1]})
        run = store.load_run(run_id)
        assert run is not None
        artifacts = run.get("artifacts") or []
        names = {a["name"] for a in artifacts}
        assert names == {"enriched_items", "run_output"}
        events = store.load_execution_log(run_id)
        artifact_events = [e for e in events if e.get("event_type") == "artifact_written"]
        assert artifact_events
        assert all("artifact_path" in e for e in artifact_events)
        artifact_dir = tmp_path / "state" / "runs" / run_id / "artifacts"
        assert (artifact_dir / "enriched_items.jsonl").exists()
        assert (artifact_dir / "run_output.json").exists()
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock
