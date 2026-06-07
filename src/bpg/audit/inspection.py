"""CLI inspection helpers for audit ledger queries and evidence export."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
import os
from pathlib import Path
from typing import Any, Mapping

from bpg.audit.postgres import (
    AuditChainVerification,
    PostgresAuditConfig,
    PostgresAuditEventSink,
)
from bpg.runtime.events import canonical_json
from bpg.runtime.observability import TracingConfig

DEFAULT_AUDIT_DSN_ENV = "BPG_AUDIT_DATABASE_URL"
AUDIT_BUNDLE_VERSION = 1

_TEMPORAL_PAYLOAD_KEYS = (
    "temporal_namespace",
    "temporal_workflow_id",
    "temporal_run_id",
    "temporal_activity_id",
    "temporal_activity_type",
    "temporal_attempt",
    "temporal_task_queue",
    "temporal_timer_id",
    "temporal_signal_name",
    "temporal_child_workflow_id",
)


class AuditSinkResolutionError(RuntimeError):
    """Raised when the Postgres audit sink cannot be configured."""


def resolve_audit_sink(
    *,
    dsn: str | None = None,
    dsn_env: str | None = None,
) -> PostgresAuditEventSink:
    """Build a Postgres audit sink from an explicit DSN or environment variable."""
    env_name = dsn_env or DEFAULT_AUDIT_DSN_ENV
    resolved_dsn = dsn or (os.getenv(env_name) if env_name else None)
    config = {
        "audit": {
            "enabled": True,
            "sink": "postgres",
            "dsn": resolved_dsn,
            "dsn_env": env_name,
        }
    }
    audit_config = PostgresAuditConfig.from_mapping(config)
    if not audit_config.dsn:
        raise AuditSinkResolutionError(
            f"Postgres audit DSN is required. Pass --dsn or set {env_name}."
        )
    try:
        sink = PostgresAuditEventSink.from_config(audit_config)
    except ValueError as exc:
        raise AuditSinkResolutionError(str(exc)) from exc
    if sink is None:
        raise AuditSinkResolutionError("Postgres audit sink is disabled.")
    return sink


def _normalize_timestamp(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return str(value)
    text = str(value)
    try:
        normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
        return str(datetime.fromisoformat(normalized))
    except ValueError:
        return text


def serialize_audit_row(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-compatible audit row with stable timestamp formatting."""
    payload = dict(row)
    if payload.get("occurred_at") is not None:
        payload["occurred_at"] = _normalize_timestamp(payload["occurred_at"])
    return payload


def audit_event_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return the fields shown by ``bpg audit show``."""
    serialized = serialize_audit_row(row)
    return {
        "sequence_id": serialized.get("sequence_id"),
        "event_type": serialized.get("event_type"),
        "occurred_at": serialized.get("occurred_at"),
        "node_id": serialized.get("node_id"),
        "actor_id": serialized.get("actor_id"),
        "trace_id": serialized.get("trace_id"),
        "event_hash": serialized.get("event_hash"),
    }


def verification_to_dict(result: AuditChainVerification) -> dict[str, Any]:
    """Serialize an audit verification result for CLI output."""
    payload = asdict(result)
    return {key: value for key, value in payload.items() if value is not None}


def extract_trace_ids(rows: list[Mapping[str, Any]]) -> list[str]:
    """Collect unique trace IDs from ordered audit rows."""
    seen: set[str] = set()
    trace_ids: list[str] = []
    for row in rows:
        trace_id = row.get("trace_id")
        if trace_id and trace_id not in seen:
            seen.add(str(trace_id))
            trace_ids.append(str(trace_id))
    return trace_ids


def _extract_temporal_from_payload(payload: Mapping[str, Any], temporal: dict[str, Any]) -> None:
    correlation = payload.get("_correlation")
    sources: list[Mapping[str, Any]] = []
    if isinstance(correlation, Mapping):
        sources.append(correlation)
    sources.append(payload)
    for source in sources:
        for key in _TEMPORAL_PAYLOAD_KEYS:
            value = source.get(key)
            if value is None:
                continue
            short_key = key.removeprefix("temporal_")
            if short_key not in temporal:
                temporal[short_key] = value


def extract_temporal_ids(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Aggregate Temporal identifiers found in audit event payloads."""
    temporal: dict[str, Any] = {}
    for row in rows:
        payload = row.get("payload") or {}
        if not isinstance(payload, Mapping):
            continue
        _extract_temporal_from_payload(payload, temporal)
    return temporal


def build_trace_summary(
    rows: list[Mapping[str, Any]],
    *,
    tracing_config: TracingConfig | None = None,
) -> dict[str, Any]:
    """Build trace correlation output for one run."""
    root_trace_id: str | None = None
    root_span_id: str | None = None
    node_spans: dict[str, str] = {}

    for row in rows:
        event_type = str(row.get("event_type") or "")
        trace_id = row.get("trace_id")
        span_id = row.get("span_id")
        node_id = row.get("node_id")

        if event_type == "run_started" and trace_id and root_trace_id is None:
            root_trace_id = str(trace_id)
            root_span_id = str(span_id) if span_id else None
        if event_type.startswith("node_") and node_id and span_id:
            node_spans.setdefault(str(node_id), str(span_id))

    exporter_target: str | None = None
    if tracing_config is not None and tracing_config.enabled and tracing_config.exporter == "otlp":
        if tracing_config.endpoint:
            exporter_target = tracing_config.endpoint
        else:
            exporter_target = (
                "http://localhost:4318/v1/traces"
                if tracing_config.protocol == "http/protobuf"
                else "http://localhost:4317"
            )

    return {
        "run_id": rows[0].get("run_id") if rows else None,
        "trace_id": root_trace_id,
        "root_span_id": root_span_id,
        "node_span_ids": dict(sorted(node_spans.items())),
        "trace_ids": extract_trace_ids(rows),
        "exporter_target": exporter_target,
        "exporter": tracing_config.exporter if tracing_config is not None else None,
        "protocol": tracing_config.protocol if tracing_config is not None else None,
    }


def build_audit_export_bundle(
    sink: PostgresAuditEventSink,
    run_id: str,
    *,
    from_checkpoint: bool = False,
    require_anchor: bool = False,
    signing_key: str | bytes | None = None,
) -> dict[str, Any]:
    """Build a deterministic audit evidence bundle for one run."""
    rows = sink.fetch_run_records(run_id)
    if not rows:
        raise ValueError(f"no audit records found for run_id={run_id!r}")

    serialized_rows = [serialize_audit_row(row) for row in rows]
    checkpoints = [
        checkpoint.to_dict()
        for checkpoint in sink.fetch_checkpoints(scope=f"run:{run_id}")
    ]

    if from_checkpoint:
        verification = sink.verify_from_latest_checkpoint(
            run_id,
            require_anchor=require_anchor,
            signing_key=signing_key,
        )
    else:
        verification = sink.verify_run(
            run_id,
            require_anchor=require_anchor,
            signing_key=signing_key,
        )

    first = serialized_rows[0]
    return {
        "bundle_version": AUDIT_BUNDLE_VERSION,
        "run_id": run_id,
        "process_name": first.get("process_name"),
        "process_version": first.get("process_version"),
        "process_hash": first.get("process_hash"),
        "events": serialized_rows,
        "checkpoints": checkpoints,
        "verification": verification_to_dict(verification),
        "trace_ids": extract_trace_ids(serialized_rows),
        "temporal": extract_temporal_ids(serialized_rows),
    }


def write_audit_export_bundle(path: Path, bundle: Mapping[str, Any]) -> None:
    """Write a canonical JSON audit export bundle."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(canonical_json(bundle) + "\n", encoding="utf-8")


def fetch_run_audit_rows(sink: PostgresAuditEventSink, run_id: str) -> list[dict[str, Any]]:
    """Fetch ordered audit rows for one run or raise when missing."""
    rows = sink.fetch_run_records(run_id)
    if not rows:
        raise ValueError(f"no audit records found for run_id={run_id!r}")
    return rows


def verify_run_audit_chain(
    sink: PostgresAuditEventSink,
    run_id: str,
    *,
    from_checkpoint: bool = False,
    require_anchor: bool = False,
    signing_key: str | bytes | None = None,
) -> AuditChainVerification:
    """Verify one run's audit chain, optionally starting at the latest checkpoint."""
    if from_checkpoint:
        return sink.verify_from_latest_checkpoint(
            run_id,
            require_anchor=require_anchor,
            signing_key=signing_key,
        )
    return sink.verify_run(
        run_id,
        require_anchor=require_anchor,
        signing_key=signing_key,
    )
