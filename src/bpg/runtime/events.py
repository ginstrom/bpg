"""Canonical runtime event schema and replay helpers."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict

EVENT_SCHEMA_VERSION = 1

EVENT_TYPES: frozenset[str] = frozenset(
    {
        "run_started",
        "node_scheduled",
        "node_started",
        "node_completed",
        "node_failed",
        "node_retry_scheduled",
        "edge_fired",
        "human_requested",
        "human_received",
        "run_completed",
        "run_failed",
    }
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _infer_event_type(entry: Dict[str, Any]) -> str:
    event_type = entry.get("event_type")
    if isinstance(event_type, str) and event_type in EVENT_TYPES:
        return event_type

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
    return "node_completed"


def normalize_event(entry: Dict[str, Any], *, run_id: str | None = None) -> Dict[str, Any]:
    """Normalize runtime events into canonical schema v1."""
    out = dict(entry)
    out["schema_version"] = EVENT_SCHEMA_VERSION
    out["event_type"] = _infer_event_type(out)
    if run_id is not None:
        out.setdefault("run_id", run_id)
    out.setdefault("timestamp", out.get("completed_at") or out.get("started_at") or _now_iso())
    return out


def replay_state_from_events(events: list[Dict[str, Any]]) -> Dict[str, Any]:
    """Rebuild derived run status from canonical events."""
    node_statuses: Dict[str, str] = {}
    run_status = "running"
    counts = Counter()

    for raw in events:
        event = normalize_event(raw)
        event_type = event["event_type"]
        counts[event_type] += 1
        node = event.get("node")
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
