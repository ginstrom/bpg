from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.providers import PROVIDER_REGISTRY
from bpg.providers.mock import MockProvider
from bpg.runtime.engine import Engine
from bpg.state.store import StateStore
from bpg_temporal import ApprovalGate, ApprovalOutcome, ApprovalRequest, ApprovalSignal, ActorIdentity
from bpg_temporal import metadata as temporal_metadata
from bpg_temporal.runtime import TemporalRuntime


def _process(tmp_path: Path):
    path = tmp_path / "process.bpg.yaml"
    path.write_text(
        """
metadata:
  name: temporal-metadata-test
  version: 1.0.0
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


def test_extract_temporal_metadata_merges_workflow_activity_and_wait_fields(monkeypatch):
    monkeypatch.setattr(
        temporal_metadata,
        "_safe_temporal_workflow_info",
        lambda: SimpleNamespace(
            namespace="payments",
            workflow_id="wf-1",
            run_id="run-1",
            task_queue="workflow-queue",
        ),
    )
    monkeypatch.setattr(
        temporal_metadata,
        "_safe_temporal_activity_info",
        lambda: SimpleNamespace(
            activity_id="activity-1",
            activity_type="ChargeCard",
            attempt="3",
            task_queue="activity-queue",
        ),
    )

    metadata = temporal_metadata.extract_temporal_metadata(
        signal_name="approval.approved",
        timer_id="timer-1",
        child_workflow_id="child-1",
    )

    assert metadata.to_event_fields() == {
        "temporal_namespace": "payments",
        "temporal_workflow_id": "wf-1",
        "temporal_run_id": "run-1",
        "temporal_activity_id": "activity-1",
        "temporal_activity_type": "ChargeCard",
        "temporal_attempt": 3,
        "temporal_task_queue": "activity-queue",
        "temporal_timer_id": "timer-1",
        "temporal_signal_name": "approval.approved",
        "temporal_child_workflow_id": "child-1",
    }


def test_temporal_runtime_enriches_node_execution_log_with_context(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(
        temporal_metadata,
        "_safe_temporal_workflow_info",
        lambda: SimpleNamespace(namespace="default", workflow_id="wf-sdk", run_id="run-sdk"),
    )
    monkeypatch.setattr(
        temporal_metadata,
        "_safe_temporal_activity_info",
        lambda: SimpleNamespace(
            activity_id="act-sdk",
            activity_type="BpgNodeActivity",
            attempt=2,
            task_queue="bpg-workers",
        ),
    )

    process = _process(tmp_path)
    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    try:
        result = TemporalRuntime().run_workflow(
            process=process,
            input_payload={},
            run_id="bpg-run-1",
        )
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock

    assert result["temporal"] == {
        "namespace": "default",
        "workflow_id": "wf-sdk",
        "run_id": "run-sdk",
        "activity_id": "act-sdk",
        "activity_type": "BpgNodeActivity",
        "attempt": 2,
        "task_queue": "bpg-workers",
    }
    assert result["execution_log"]
    assert all(entry["temporal_workflow_id"] == "wf-sdk" for entry in result["execution_log"])
    assert all(entry["temporal_activity_id"] == "act-sdk" for entry in result["execution_log"])
    assert all(entry["temporal_attempt"] == 2 for entry in result["execution_log"])


def test_temporal_backend_persists_workflow_metadata_on_run_lifecycle_events(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setattr(temporal_metadata, "_safe_temporal_workflow_info", lambda: None)
    monkeypatch.setattr(temporal_metadata, "_safe_temporal_activity_info", lambda: None)

    process = _process(tmp_path)
    store = StateStore(tmp_path / "state")
    store.save_process(compile_process(process))
    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    try:
        run_id = Engine(process=process, state_store=store, backend="temporal").trigger({})
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock

    events = store.load_execution_log(run_id)
    run_events = [
        event
        for event in events
        if event["event_type"] in {"run_started", "run_completed"}
    ]
    assert [event["event_type"] for event in run_events] == ["run_started", "run_completed"]
    assert all(event["temporal_namespace"] == "default" for event in run_events)
    assert all(event["temporal_workflow_id"] == run_id for event in run_events)


def test_approval_gate_records_signal_and_timer_temporal_metadata(monkeypatch):
    monkeypatch.setattr(temporal_metadata, "_safe_temporal_workflow_info", lambda: None)
    monkeypatch.setattr(temporal_metadata, "_safe_temporal_activity_info", lambda: None)
    request = ApprovalRequest(
        request_id="req-1",
        workflow_id="wf-approval",
        node_id="review",
        correlation_id="corr-1",
        subject="Review",
        payload={},
    )
    gate = ApprovalGate(request)

    gate.send_signal(
        ApprovalSignal(
            outcome=ApprovalOutcome.APPROVED,
            actor=ActorIdentity(actor_id="alice"),
        )
    )

    assert gate.query_state()["temporal"] == {
        "temporal_workflow_id": "wf-approval",
        "temporal_signal_name": "approval.approved",
    }

    timeout_gate = ApprovalGate(request)
    timeout_gate.apply_timeout()
    assert timeout_gate.query_state()["temporal"] == {
        "temporal_workflow_id": "wf-approval",
        "temporal_timer_id": "approval.req-1.timeout",
    }
