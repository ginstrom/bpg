"""Temporal metadata extraction and event enrichment helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

from bpg.runtime.events import BpgEvent


TEMPORAL_EVENT_FIELDS: tuple[str, ...] = (
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


@dataclass(frozen=True)
class TemporalMetadata:
    """Portable subset of Temporal workflow/activity/signal/timer metadata."""

    namespace: str | None = None
    workflow_id: str | None = None
    run_id: str | None = None
    activity_id: str | None = None
    activity_type: str | None = None
    attempt: int | None = None
    task_queue: str | None = None
    timer_id: str | None = None
    signal_name: str | None = None
    child_workflow_id: str | None = None

    def to_event_fields(self) -> dict[str, Any]:
        fields = {
            "temporal_namespace": self.namespace,
            "temporal_workflow_id": self.workflow_id,
            "temporal_run_id": self.run_id,
            "temporal_activity_id": self.activity_id,
            "temporal_activity_type": self.activity_type,
            "temporal_attempt": self.attempt,
            "temporal_task_queue": self.task_queue,
            "temporal_timer_id": self.timer_id,
            "temporal_signal_name": self.signal_name,
            "temporal_child_workflow_id": self.child_workflow_id,
        }
        return {key: value for key, value in fields.items() if value is not None}

    def to_result_metadata(self) -> dict[str, Any]:
        fields = self.to_event_fields()
        return {key.removeprefix("temporal_"): value for key, value in fields.items()}


def _get_attr(source: Any, *names: str) -> Any:
    for name in names:
        if isinstance(source, Mapping) and name in source:
            return source[name]
        value = getattr(source, name, None)
        if value is not None:
            return value
    return None


def _safe_temporal_workflow_info() -> Any | None:
    try:
        from temporalio import workflow

        return workflow.info()
    except Exception:  # noqa: BLE001
        return None


def _safe_temporal_activity_info() -> Any | None:
    try:
        from temporalio import activity

        return activity.info()
    except Exception:  # noqa: BLE001
        return None


def extract_temporal_metadata(
    *,
    namespace: str | None = None,
    workflow_id: str | None = None,
    run_id: str | None = None,
    activity_id: str | None = None,
    activity_type: str | None = None,
    attempt: int | None = None,
    task_queue: str | None = None,
    timer_id: str | None = None,
    signal_name: str | None = None,
    child_workflow_id: str | None = None,
) -> TemporalMetadata:
    """Extract Temporal identifiers from SDK context, with explicit fallbacks."""

    workflow_info = _safe_temporal_workflow_info()
    activity_info = _safe_temporal_activity_info()

    raw_attempt = attempt if attempt is not None else _get_attr(activity_info, "attempt")
    if raw_attempt is not None:
        try:
            raw_attempt = int(raw_attempt)
        except (TypeError, ValueError):
            raw_attempt = None

    return TemporalMetadata(
        namespace=namespace
        or _get_attr(workflow_info, "namespace")
        or _get_attr(activity_info, "workflow_namespace", "namespace"),
        workflow_id=workflow_id
        or _get_attr(workflow_info, "workflow_id")
        or _get_attr(activity_info, "workflow_id"),
        run_id=run_id
        or _get_attr(workflow_info, "run_id", "workflow_run_id")
        or _get_attr(activity_info, "workflow_run_id", "run_id"),
        activity_id=activity_id or _get_attr(activity_info, "activity_id"),
        activity_type=activity_type
        or _get_attr(activity_info, "activity_type")
        or _get_attr(activity_info, "activity_type_name"),
        attempt=raw_attempt,
        task_queue=task_queue
        or _get_attr(activity_info, "task_queue")
        or _get_attr(workflow_info, "task_queue"),
        timer_id=timer_id,
        signal_name=signal_name,
        child_workflow_id=child_workflow_id,
    )


def enrich_event_with_temporal_metadata(
    event: BpgEvent,
    metadata: TemporalMetadata | Mapping[str, Any],
) -> BpgEvent:
    """Return ``event`` with missing Temporal fields filled from metadata."""

    fields = (
        metadata.to_event_fields()
        if isinstance(metadata, TemporalMetadata)
        else {key: metadata.get(key) for key in TEMPORAL_EVENT_FIELDS}
    )
    update = {
        key: value
        for key, value in fields.items()
        if value is not None and getattr(event, key, None) is None
    }
    if not update:
        return event
    return event.model_copy(update=update)


def enrich_run_event_with_temporal_metadata(
    event: Mapping[str, Any],
    metadata: TemporalMetadata | Mapping[str, Any],
) -> dict[str, Any]:
    """Return a dict-shaped runtime event enriched with Temporal fields."""

    fields = (
        metadata.to_event_fields()
        if isinstance(metadata, TemporalMetadata)
        else {key: metadata.get(key) for key in TEMPORAL_EVENT_FIELDS}
    )
    enriched = dict(event)
    for key, value in fields.items():
        if value is not None:
            enriched.setdefault(key, value)
    return enriched
