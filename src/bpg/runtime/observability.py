"""Structured event emission and run replay for BPG process observability.

Every node transition in the runtime emits a canonical :class:`BpgEvent` to a
pluggable :class:`EventSink`. This decouples observability concerns from
execution logic and lets operators plug in log aggregators, metrics sinks, or
replay buffers without touching the engine.

Event types
-----------
- ``node_started``  — emitted just before the provider is invoked
- ``node_retry_scheduled`` — emitted between retry attempts
- ``node_completed`` — emitted on success
- ``node_failed``   — emitted after retries are exhausted or a non-retryable error
- ``node_skipped``  — emitted when no incoming edge fires

Replay
------
:func:`replay_run` walks a completed ``execution_log`` (from :class:`RunState`)
and re-emits the corresponding :class:`RunEvent` to any sink.  This lets you
reconstruct what happened in a run purely from the persisted log — useful for
post-mortem debugging without re-executing any providers.

Usage::

    sink = ListEventSink()
    runtime = LangGraphRuntime(ir=ir, providers=..., event_sink=sink)
    state = runtime.run(input_payload={...})

    # inspect every event that fired
    for event in sink.events:
        print(event["event_type"], event["node"], event.get("error"))

    # or replay from the persisted execution_log later
    replay_run(state["execution_log"], run_id=state["run_id"],
               process_name=state["process_name"], sink=LoggingEventSink())
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Optional

from typing_extensions import TypedDict

from bpg.runtime.events import BpgEvent, event_from_run_event


# ---------------------------------------------------------------------------
# RunEvent schema
# ---------------------------------------------------------------------------

class RunEvent(TypedDict, total=False):
    """Structured event emitted at every node state transition.

    Required fields (always present):
        event_type: One of the node transition event names listed above.
        run_id: Globally unique run identifier.
        process_name: Name of the owning process.
        node: Node instance name.
        timestamp: UTC ISO 8601 timestamp of the transition.

    Optional fields (present only where relevant):
        attempt: 1-based attempt number (present on ``node_retrying``).
        delay_seconds: Backoff sleep time before next attempt (``node_retrying``).
        input: Resolved input payload (``node_started``, ``node_retrying``).
        output: Provider output payload (``node_completed``).
        error: Human-readable error message (``node_failed``, ``node_timed_out``).
        error_code: Machine-readable error code (``node_failed``).
        idempotency_key: Idempotency key for the invocation.
        status: The final NodeStatus string (mirrors ``node_statuses`` in RunState).
    """

    # --- required ---
    event_type: str
    run_id: str
    process_name: str
    node: str
    timestamp: str

    # --- optional ---
    attempt: int
    delay_seconds: float
    input: Dict[str, Any]
    output: Dict[str, Any]
    error: str
    error_code: str
    idempotency_key: str
    status: str


# ---------------------------------------------------------------------------
# EventSink ABC
# ---------------------------------------------------------------------------

class EventSink(ABC):
    """Abstract base class for structured event receivers.

    Concrete implementations forward events to log aggregators, metrics
    pipelines, in-memory buffers, etc.
    """

    @abstractmethod
    def emit(self, event: BpgEvent) -> None:
        """Receive and process a single canonical :class:`BpgEvent`.

        Implementations MUST NOT raise — swallow or log exceptions internally
        so that a sink failure never disrupts process execution.

        Args:
            event: The structured event to process.
        """


# ---------------------------------------------------------------------------
# Built-in sinks
# ---------------------------------------------------------------------------

class NoopEventSink(EventSink):
    """Sink that discards all events.  Used as the default when no sink is supplied."""

    def emit(self, event: BpgEvent) -> None:  # noqa: ARG002
        pass


class EventSinkGroup(EventSink):
    """Fan out canonical events to multiple sinks in deterministic order."""

    def __init__(self, sinks: Iterable[EventSink]) -> None:
        self._sinks = list(sinks)

    def emit(self, event: BpgEvent) -> None:
        for sink in self._sinks:
            try:
                sink.emit(event)
            except Exception:  # noqa: BLE001
                continue


class LegacyRunEventAdapter(EventSink):
    """Adapter for old sinks that still expect ``RunEvent`` dictionaries."""

    def __init__(self, sink: Any) -> None:
        self._sink = sink

    def emit(self, event: BpgEvent) -> None:
        try:
            self._sink.emit(event_to_run_event(event))
        except Exception:  # noqa: BLE001
            pass


class ListEventSink(EventSink):
    """Sink that accumulates events in memory.

    Useful for testing and debugging: inspect ``sink.events`` after a run to
    see every transition in order.

    Attributes:
        events: Ordered list of all emitted events.
    """

    def __init__(self) -> None:
        self.canonical_events: List[BpgEvent] = []
        self.events: List[RunEvent] = []

    def emit(self, event: BpgEvent) -> None:
        self.canonical_events.append(event)
        self.events.append(event_to_run_event(event))

    def by_type(self, event_type: str) -> List[RunEvent]:
        """Return all events matching the given ``event_type``."""
        return [e for e in self.events if e.get("event_type") == event_type]

    def canonical_by_type(self, event_type: str) -> List[BpgEvent]:
        """Return all canonical events matching the given ``event_type``."""
        return [e for e in self.canonical_events if e.event_type == event_type]

    def for_node(self, node: str) -> List[RunEvent]:
        """Return all events for the given node name."""
        return [e for e in self.events if e.get("node") == node]


class LoggingEventSink(EventSink):
    """Sink that writes each event as a single-line JSON record via Python's
    :mod:`logging` module.

    All events are emitted at ``INFO`` level unless they represent a failure
    (``node_failed``), which are emitted at ``WARNING``.

    Args:
        logger: Logger to use.  Defaults to ``logging.getLogger("bpg.events")``.
    """

    def __init__(self, logger: Optional[logging.Logger] = None) -> None:
        self._logger = logger or logging.getLogger("bpg.events")

    def emit(self, event: BpgEvent) -> None:
        try:
            line = event.to_canonical_json()
            if event.event_type == "node_failed":
                self._logger.warning(line)
            else:
                self._logger.info(line)
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------

# Map the NodeStatus value stored in execution_log["status"] to an event_type.
_STATUS_TO_EVENT: Dict[str, str] = {
    "completed": "node_completed",
    "failed": "node_failed",
    "skipped": "node_skipped",
    "timed_out": "node_failed",
    "running": "node_started",
    "pending": "node_started",
    "cancelled": "node_failed",
}


def event_to_run_event(event: BpgEvent) -> RunEvent:
    """Project a canonical event into the historical dict-shaped runtime view."""
    payload = dict(event.payload or {})
    legacy: RunEvent = {
        "event_type": event.event_type,
        "run_id": event.run_id,
        "process_name": event.process_name,
        "timestamp": event.occurred_at,
    }
    if event.node_id is not None:
        legacy["node"] = event.node_id
    for key in (
        "attempt",
        "delay_seconds",
        "input",
        "output",
        "error",
        "error_code",
        "idempotency_key",
        "status",
        "effective_status",
        "synthetic",
        "cache_hit",
    ):
        if key in payload:
            legacy[key] = payload[key]  # type: ignore[typeddict-unknown-key]
    if event.tags:
        legacy["tags"] = dict(event.tags)  # type: ignore[typeddict-unknown-key]
    return legacy


def run_event_to_event(
    event: RunEvent,
    *,
    process_version: str,
    process_hash: str,
    engine_backend: str,
) -> BpgEvent:
    """Build a canonical event from the historical runtime event dictionary."""
    return event_from_run_event(
        event,
        process_version=process_version,
        process_hash=process_hash,
        engine_backend=engine_backend,
    )


def replay_run(
    execution_log: List[Dict[str, Any]],
    run_id: str,
    process_name: str,
    sink: EventSink,
    *,
    process_version: str = "unknown",
    process_hash: str = "unknown",
    engine_backend: str = "replay",
) -> None:
    """Replay a completed execution log by re-emitting structured events.

    Walks the ``execution_log`` list in order (as recorded during the run) and
    emits a :class:`RunEvent` for each entry.  No providers are invoked — this
    is a pure, read-only replay of what already happened.

    Useful for:
    - Post-mortem debugging: feed ``LoggingEventSink`` to get a structured trace
    - Testing observability pipelines with real recorded data
    - Reconstructing a run from a persisted log stored externally

    Args:
        execution_log: The ``execution_log`` list from a completed
            :class:`~bpg.runtime.state.RunState`.
        run_id: The ``run_id`` of the original run.
        process_name: The ``process_name`` of the original run.
        sink: Destination for the re-emitted events.
    """
    for entry in execution_log:
        status = entry.get("status", "")
        event_type = _STATUS_TO_EVENT.get(status, f"node_{status}")

        event: RunEvent = {
            "event_type": event_type,
            "run_id": run_id,
            "process_name": process_name,
            "node": entry["node"],
            "timestamp": entry.get("timestamp", ""),
            "status": status,
        }

        if "input" in entry:
            event["input"] = entry["input"]
        if "output" in entry:
            event["output"] = entry["output"]
        if "error" in entry:
            event["error"] = entry["error"]
        if "idempotency_key" in entry:
            event["idempotency_key"] = entry["idempotency_key"]

        sink.emit(
            run_event_to_event(
                event,
                process_version=process_version,
                process_hash=process_hash,
                engine_backend=engine_backend,
            )
        )
