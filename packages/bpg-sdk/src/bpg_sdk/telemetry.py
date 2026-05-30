"""Telemetry field name conventions for BPG framework observability.

These constants define the canonical attribute names used in OpenTelemetry
spans, metrics, and structured log records emitted by BPG packages.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


class TelemetryFields:
    """Stable field name constants for BPG telemetry."""

    WORKFLOW_ID = "bpg.workflow_id"
    NODE_ID = "bpg.node_id"
    ACTOR_ID = "bpg.actor_id"
    POLICY_ID = "bpg.policy_id"
    CORRELATION_ID = "bpg.correlation_id"
    EXTERNAL_REF = "bpg.external_ref"
    RUN_ID = "bpg.run_id"
    PROCESS_NAME = "bpg.process_name"
    AUDIT_EVENT_TYPE = "bpg.audit.event_type"

    SPAN_WORKFLOW_RUN = "bpg.workflow.run"
    SPAN_NODE_EXECUTE = "bpg.node.execute"
    SPAN_APPROVAL_WAIT = "bpg.approval.wait"

    METRIC_APPROVAL_DURATION = "bpg.approval.duration_seconds"
    METRIC_NODE_DURATION = "bpg.node.duration_seconds"
    METRIC_POLICY_DECISIONS = "bpg.policy.decisions_total"


def build_span_attributes(
    *,
    workflow_id: str,
    node_id: str,
    actor_id: str | None = None,
    policy_id: str | None = None,
    correlation_id: str | None = None,
    external_ref: str | None = None,
    run_id: str | None = None,
    process_name: str | None = None,
) -> dict[str, str]:
    """Build a dict of OTEL-compatible span attributes using BPG field conventions."""
    attrs: dict[str, str] = {
        TelemetryFields.WORKFLOW_ID: workflow_id,
        TelemetryFields.NODE_ID: node_id,
    }
    if actor_id is not None:
        attrs[TelemetryFields.ACTOR_ID] = actor_id
    if policy_id is not None:
        attrs[TelemetryFields.POLICY_ID] = policy_id
    if correlation_id is not None:
        attrs[TelemetryFields.CORRELATION_ID] = correlation_id
    if external_ref is not None:
        attrs[TelemetryFields.EXTERNAL_REF] = external_ref
    if run_id is not None:
        attrs[TelemetryFields.RUN_ID] = run_id
    if process_name is not None:
        attrs[TelemetryFields.PROCESS_NAME] = process_name
    return attrs


def build_log_record(
    *,
    event_type: str,
    workflow_id: str,
    node_id: str,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a structured log record with BPG field conventions."""
    record: dict[str, Any] = {
        "event_type": event_type,
        TelemetryFields.WORKFLOW_ID: workflow_id,
        TelemetryFields.NODE_ID: node_id,
        TelemetryFields.AUDIT_EVENT_TYPE: event_type,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        record.update(extra)
    return record
