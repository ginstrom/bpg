import pytest
from pydantic import ValidationError

from bpg.runtime.events import (
    BpgEvent,
    EVENT_SCHEMA_VERSION,
    event_from_audit_event,
    event_from_run_event,
    normalize_event,
    replay_state_from_events,
    sha256_json,
)
from bpg_sdk.audit import AuditEvent, AuditEventType


def test_normalize_event_adds_schema_version_and_event_type():
    ev = normalize_event({"event": "node_failed", "node": "triage", "status": "failed"}, run_id="r1")
    assert ev["schema_version"] == EVENT_SCHEMA_VERSION
    assert ev["event_type"] == "node_failed"
    assert ev["run_id"] == "r1"
    assert "timestamp" in ev


def test_replay_state_from_events_reconstructs_statuses():
    events = [
        {"event_type": "run_started"},
        {"event_type": "node_scheduled", "node": "extract"},
        {"event_type": "node_completed", "node": "extract", "status": "completed"},
        {"event_type": "node_scheduled", "node": "review"},
        {"event_type": "node_completed", "node": "review", "status": "skipped"},
        {"event_type": "run_completed"},
    ]
    replayed = replay_state_from_events(events)
    assert replayed["run_status"] == "completed"
    assert replayed["node_statuses"]["extract"] == "completed"
    assert replayed["node_statuses"]["review"] == "skipped"
    assert replayed["event_counts"]["node_completed"] == 2


def test_bpg_event_requires_supported_event_type():
    with pytest.raises(ValidationError):
        BpgEvent(
            event_id="evt-1",
            event_type="unknown",
            occurred_at="2026-01-01T00:00:00+00:00",
            run_id="run-1",
            process_name="proc",
            process_version="1.0.0",
            process_hash="sha256:abc",
            engine_backend="local",
        )


def test_bpg_event_allows_extension_event_type():
    event = BpgEvent(
        event_id="evt-1",
        event_type="extension.vendor_custom",
        occurred_at="2026-01-01T00:00:00+00:00",
        run_id="run-1",
        process_name="proc",
        process_version="1.0.0",
        process_hash="sha256:abc",
        engine_backend="local",
    )
    assert event.event_type == "extension.vendor_custom"


def test_bpg_event_serialization_is_deterministic():
    first = BpgEvent(
        event_id="evt-1",
        event_type="node_completed",
        occurred_at="2026-01-01T00:00:00+00:00",
        run_id="run-1",
        process_name="proc",
        process_version="1.0.0",
        process_hash="sha256:abc",
        engine_backend="local",
        node_id="node-a",
        payload={"b": 2, "a": 1},
        tags={"z": "last", "a": "first"},
    )
    second = BpgEvent(
        event_id="evt-1",
        event_type="node_completed",
        occurred_at="2026-01-01T00:00:00+00:00",
        run_id="run-1",
        process_name="proc",
        process_version="1.0.0",
        process_hash="sha256:abc",
        engine_backend="local",
        node_id="node-a",
        payload={"a": 1, "b": 2},
        tags={"a": "first", "z": "last"},
    )
    assert first.to_canonical_json() == second.to_canonical_json()


def test_legacy_event_type_is_normalized_to_canonical_name():
    ev = normalize_event({"event_type": "human_requested", "node": "review"}, run_id="r1")
    assert ev["event_type"] == "approval_requested"


def test_run_event_adapter_builds_canonical_event_and_hashes_payloads():
    event = event_from_run_event(
        {
            "event_id": "evt-run-1",
            "event_type": "node_retrying",
            "run_id": "run-1",
            "process_name": "proc",
            "node": "extract",
            "timestamp": "2026-01-01T00:00:00+00:00",
            "temporal_namespace": "default",
            "temporal_workflow_id": "wf-1",
            "temporal_run_id": "trun-1",
            "temporal_activity_id": "act-1",
            "temporal_activity_type": "BpgNodeActivity",
            "temporal_attempt": 2,
            "temporal_task_queue": "bpg-workers",
            "input": {"email": "hello"},
            "error": "temporary failure",
            "status": "running",
        },
        process_version="1.0.0",
        process_hash="sha256:abc",
        engine_backend="local",
    )

    assert event.event_type == "node_retry_scheduled"
    assert event.node_id == "extract"
    assert event.temporal_workflow_id == "wf-1"
    assert event.temporal_activity_id == "act-1"
    assert event.temporal_activity_type == "BpgNodeActivity"
    assert event.temporal_attempt == 2
    assert event.temporal_task_queue == "bpg-workers"
    assert event.input_sha256 == sha256_json({"email": "hello"})
    assert event.payload_sha256 == sha256_json(
        {"input": {"email": "hello"}, "error": "temporary failure", "status": "running"}
    )


def test_audit_event_adapter_maps_sdk_approval_decision():
    audit_event = AuditEvent(
        event_type=AuditEventType.REJECTED,
        workflow_id="wf-1",
        node_id="approval",
        timestamp="2026-01-01T00:00:00+00:00",
        actor_id="alice",
        policy_id="requires-manager",
        correlation_id="corr-1",
        external_ref="ticket-1",
        reason="Budget cap exceeded",
        payload={"amount": 5000},
    )

    event = event_from_audit_event(
        audit_event,
        process_name="proc",
        process_version="1.0.0",
        process_hash="sha256:abc",
        engine_backend="local",
    )

    assert event.event_type == "approval_resolved"
    assert event.run_id == "wf-1"
    assert event.node_id == "approval"
    assert event.actor_id == "alice"
    assert event.policy_id == "requires-manager"
    assert event.payload == {
        "amount": 5000,
        "reason": "Budget cap exceeded",
        "decision": "rejected",
    }
