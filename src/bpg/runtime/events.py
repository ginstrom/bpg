"""Canonical runtime event schema and replay helpers."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

EVENT_SCHEMA_VERSION = 1

EVENT_TYPES: frozenset[str] = frozenset(
    {
        "run_started",
        "run_completed",
        "run_failed",
        "node_scheduled",
        "node_started",
        "node_completed",
        "node_failed",
        "node_skipped",
        "node_retry_scheduled",
        "edge_fired",
        "policy_checked",
        "policy_blocked",
        "approval_requested",
        "approval_resolved",
        "approval_timed_out",
        "artifact_written",
        "audit_checkpointed",
    }
)

LEGACY_EVENT_TYPE_ALIASES: dict[str, str] = {
    "human_requested": "approval_requested",
    "human_received": "approval_resolved",
    "node_retrying": "node_retry_scheduled",
    "node_timed_out": "node_failed",
    "approved": "approval_resolved",
    "rejected": "approval_resolved",
    "escalated": "approval_resolved",
    "timed_out": "approval_timed_out",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_event_id() -> str:
    return str(uuid4())


def _canonical_event_type(event_type: str) -> str:
    return LEGACY_EVENT_TYPE_ALIASES.get(event_type, event_type)


def canonical_json(value: Any) -> str:
    """Return deterministic JSON for hashing, persistence, and tests."""
    return json.dumps(value, default=str, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def sha256_json(value: Any) -> str:
    """Return the SHA-256 digest of deterministic JSON for ``value``."""
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


class BpgEvent(BaseModel):
    """Canonical BPG event envelope consumed by tracing, audit, and replay adapters."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = EVENT_SCHEMA_VERSION
    event_id: str = Field(default_factory=_new_event_id)
    event_type: str
    occurred_at: str = Field(default_factory=_now_iso)
    run_id: str
    process_name: str
    process_version: str
    process_hash: str
    engine_backend: str

    node_id: str | None = None
    node_type: str | None = None
    node_package: str | None = None
    trace_id: str | None = None
    span_id: str | None = None
    parent_span_id: str | None = None
    correlation_id: str | None = None
    causation_id: str | None = None
    actor_id: str | None = None
    actor_type: str | None = None
    policy_id: str | None = None
    external_ref: str | None = None
    temporal_namespace: str | None = None
    temporal_workflow_id: str | None = None
    temporal_run_id: str | None = None
    temporal_activity_id: str | None = None
    temporal_activity_type: str | None = None
    temporal_attempt: int | None = None
    temporal_task_queue: str | None = None
    temporal_timer_id: str | None = None
    temporal_signal_name: str | None = None
    temporal_child_workflow_id: str | None = None
    provider_id: str | None = None
    provider_job_id: str | None = None
    artifact_name: str | None = None
    artifact_sha256: str | None = None
    input_sha256: str | None = None
    output_sha256: str | None = None
    redaction_policy_id: str | None = None
    redacted_field_paths: list[str] = Field(default_factory=list)
    payload: dict[str, Any] | None = None
    payload_sha256: str | None = None
    tags: dict[str, str] = Field(default_factory=dict)

    @field_validator("schema_version")
    @classmethod
    def _validate_schema_version(cls, value: int) -> int:
        if value != EVENT_SCHEMA_VERSION:
            raise ValueError(f"schema_version must be {EVENT_SCHEMA_VERSION}")
        return value

    @field_validator("event_type", mode="before")
    @classmethod
    def _validate_event_type(cls, value: Any) -> str:
        if hasattr(value, "value"):
            value = value.value
        if not isinstance(value, str):
            raise TypeError("event_type must be a string")
        event_type = _canonical_event_type(value)
        if event_type not in EVENT_TYPES and not event_type.startswith("extension."):
            raise ValueError(f"unsupported event_type: {value}")
        return event_type

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-compatible dictionary without unset optional fields."""
        return self.model_dump(mode="json", exclude_none=True)

    def to_canonical_json(self) -> str:
        """Serialize the event deterministically."""
        return canonical_json(self.to_dict())


def _infer_event_type(entry: Dict[str, Any]) -> str:
    event_type = entry.get("event_type")
    if isinstance(event_type, str):
        canonical_type = _canonical_event_type(event_type)
        if canonical_type in EVENT_TYPES or canonical_type.startswith("extension."):
            return canonical_type

    event = entry.get("event")
    if event == "node_scheduled":
        return "node_scheduled"
    if event == "node_failed":
        return "node_failed"
    if event == "node_completed":
        return "node_completed"
    if event == "node_started":
        return "node_started"
    if event == "node_retrying":
        return "node_retry_scheduled"
    if event == "node_skipped":
        return "node_skipped"
    if event == "human_requested":
        return "approval_requested"
    if event == "human_received":
        return "approval_resolved"
    return "node_completed"


def normalize_event(entry: Dict[str, Any], *, run_id: str | None = None) -> Dict[str, Any]:
    """Normalize runtime events into canonical schema v1."""
    out = dict(entry)
    out["schema_version"] = EVENT_SCHEMA_VERSION
    out["event_type"] = _infer_event_type(out)
    if run_id is not None:
        out.setdefault("run_id", run_id)
    out.setdefault("timestamp", out.get("completed_at") or out.get("started_at") or _now_iso())
    out.setdefault("occurred_at", out["timestamp"])
    return out


def event_from_run_event(
    event: Mapping[str, Any],
    *,
    process_version: str,
    process_hash: str,
    engine_backend: str,
) -> BpgEvent:
    """Convert an existing runtime ``RunEvent``-style mapping to ``BpgEvent``."""
    payload: dict[str, Any] = {}
    if "input" in event:
        payload["input"] = event["input"]
    if "output" in event:
        payload["output"] = event["output"]
    if "error" in event:
        payload["error"] = event["error"]
    if "error_code" in event:
        payload["error_code"] = event["error_code"]
    if "status" in event:
        payload["status"] = event["status"]
    for key in (
        "attempt",
        "delay_seconds",
        "idempotency_key",
        "effective_status",
        "synthetic",
        "cache_hit",
    ):
        if key in event:
            payload[key] = event[key]

    kwargs: dict[str, Any] = {
        "event_type": event.get("event_type"),
        "occurred_at": event.get("occurred_at") or event.get("timestamp") or _now_iso(),
        "run_id": event.get("run_id"),
        "process_name": event.get("process_name"),
        "process_version": process_version,
        "process_hash": process_hash,
        "engine_backend": engine_backend,
        "node_id": event.get("node") or event.get("node_id"),
        "node_type": event.get("node_type"),
        "node_package": event.get("node_package"),
        "correlation_id": event.get("correlation_id"),
        "causation_id": event.get("causation_id"),
        "temporal_namespace": event.get("temporal_namespace"),
        "temporal_workflow_id": event.get("temporal_workflow_id"),
        "temporal_run_id": event.get("temporal_run_id"),
        "temporal_activity_id": event.get("temporal_activity_id"),
        "temporal_activity_type": event.get("temporal_activity_type"),
        "temporal_attempt": event.get("temporal_attempt"),
        "temporal_task_queue": event.get("temporal_task_queue"),
        "temporal_timer_id": event.get("temporal_timer_id"),
        "temporal_signal_name": event.get("temporal_signal_name"),
        "temporal_child_workflow_id": event.get("temporal_child_workflow_id"),
        "provider_id": event.get("provider_id"),
        "provider_job_id": event.get("provider_job_id"),
        "actor_id": event.get("actor_id"),
        "actor_type": event.get("actor_type"),
        "policy_id": event.get("policy_id"),
        "payload": payload or None,
        "tags": dict(event.get("tags") or {}),
    }
    if "event_id" in event:
        kwargs["event_id"] = event["event_id"]
    if "input" in event:
        kwargs["input_sha256"] = sha256_json(event["input"])
    if "output" in event:
        kwargs["output_sha256"] = sha256_json(event["output"])
    if payload:
        kwargs["payload_sha256"] = sha256_json(payload)
    return BpgEvent(**kwargs)


def event_from_audit_event(
    event: Any,
    *,
    process_name: str,
    process_version: str,
    process_hash: str,
    engine_backend: str,
) -> BpgEvent:
    """Convert an SDK ``AuditEvent`` or equivalent object to ``BpgEvent``.

    This accepts a duck-typed object so the core runtime does not need to import
    the SDK package.
    """
    raw_type = getattr(event, "event_type")
    event_type = getattr(raw_type, "value", raw_type)
    payload = dict(getattr(event, "payload", {}) or {})
    reason = getattr(event, "reason", None)
    if reason is not None:
        payload.setdefault("reason", reason)
    if event_type in {"approved", "rejected", "escalated"}:
        payload.setdefault("decision", event_type)

    kwargs: dict[str, Any] = {
        "event_type": event_type,
        "occurred_at": getattr(event, "timestamp"),
        "run_id": getattr(event, "workflow_id"),
        "process_name": process_name,
        "process_version": process_version,
        "process_hash": process_hash,
        "engine_backend": engine_backend,
        "node_id": getattr(event, "node_id"),
        "actor_id": getattr(event, "actor_id", None),
        "policy_id": getattr(event, "policy_id", None),
        "correlation_id": getattr(event, "correlation_id", None),
        "external_ref": getattr(event, "external_ref", None),
        "payload": payload or None,
        "tags": {"source": "sdk_audit"},
    }
    event_id = getattr(event, "event_id", None)
    if event_id is not None:
        kwargs["event_id"] = event_id
    if payload:
        kwargs["payload_sha256"] = sha256_json(payload)
    return BpgEvent(**kwargs)


def replay_state_from_events(events: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Rebuild derived run status from canonical events."""
    node_statuses: Dict[str, str] = {}
    run_status = "running"
    counts = Counter()

    for raw in events:
        event = normalize_event(raw)
        event_type = event["event_type"]
        counts[event_type] += 1
        node = event.get("node") or event.get("node_id")
        if isinstance(node, str):
            if event_type in {"node_scheduled", "node_started"}:
                node_statuses[node] = "running"
            elif event_type == "node_completed":
                status = str(event.get("status", "completed"))
                node_statuses[node] = status
            elif event_type == "node_failed":
                status = str(event.get("status", "failed"))
                node_statuses[node] = status

        if event_type == "run_completed":
            run_status = "completed"
        elif event_type == "run_failed":
            run_status = "failed"

    if run_status == "running":
        if any(status in {"failed", "timed_out"} for status in node_statuses.values()):
            run_status = "failed"
        elif node_statuses and all(
            status in {"completed", "skipped"} for status in node_statuses.values()
        ):
            run_status = "completed"

    return {
        "run_status": run_status,
        "node_statuses": node_statuses,
        "event_counts": dict(counts),
        "event_total": len(events),
    }
