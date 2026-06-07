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

from dataclasses import dataclass
from datetime import datetime
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Iterable, List, Literal, Mapping, Optional

from typing_extensions import TypedDict

from bpg.runtime.events import BpgEvent, canonical_json, event_from_run_event


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
    def emit(self, event: BpgEvent) -> BpgEvent | None:
        """Receive and process a single canonical :class:`BpgEvent`.

        Implementations should swallow or log exceptions internally unless they
        enforce an explicit fail-run policy, such as durable audit capture.

        Args:
            event: The structured event to process.

        Returns:
            Optionally, an enriched event for downstream sinks in an
            :class:`EventSinkGroup`. Most sinks return ``None``.
        """


# ---------------------------------------------------------------------------
# Built-in sinks
# ---------------------------------------------------------------------------

class NoopEventSink(EventSink):
    """Sink that discards all events.  Used as the default when no sink is supplied."""

    def emit(self, event: BpgEvent) -> None:  # noqa: ARG002
        return None


class EventSinkGroup(EventSink):
    """Fan out canonical events to multiple sinks in deterministic order."""

    def __init__(self, sinks: Iterable[EventSink]) -> None:
        self._sinks = list(sinks)

    def emit(self, event: BpgEvent) -> None:
        current = event
        for sink in self._sinks:
            try:
                enriched = sink.emit(current)
            except Exception as exc:  # noqa: BLE001
                if getattr(exc, "audit_failure_policy", None) == "fail_run":
                    raise
                continue
            if isinstance(enriched, BpgEvent):
                current = enriched


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


TracingExporter = Literal["otlp", "none"]
TracingProtocol = Literal["grpc", "http/protobuf"]
TracingSample = Literal["always", "never"]


@dataclass(frozen=True)
class TracingConfig:
    """Runtime OpenTelemetry tracing configuration."""

    enabled: bool = False
    exporter: TracingExporter = "otlp"
    endpoint: str | None = None
    protocol: TracingProtocol = "grpc"
    sample: TracingSample = "always"
    emit_input: bool = False
    emit_output: bool = False
    service_name: str = "bpg"

    @classmethod
    def from_mapping(cls, config: Dict[str, Any] | None) -> "TracingConfig":
        """Build tracing config from either a root or tracing-only mapping."""
        if not config:
            return cls()
        raw: Dict[str, Any]
        if "observability" in config:
            raw = dict((config.get("observability") or {}).get("tracing") or {})
        elif "tracing" in config:
            raw = dict(config.get("tracing") or {})
        else:
            raw = dict(config)

        protocol = str(raw.get("protocol", "grpc")).lower()
        if protocol in {"http", "http/protobuf", "protobuf"}:
            protocol = "http/protobuf"
        elif protocol != "grpc":
            protocol = "grpc"

        exporter = str(raw.get("exporter", "otlp")).lower()
        if exporter != "otlp":
            exporter = "none"

        sample = str(raw.get("sample", "always")).lower()
        if sample != "never":
            sample = "always"

        return cls(
            enabled=bool(raw.get("enabled", False)),
            exporter=exporter,  # type: ignore[arg-type]
            endpoint=raw.get("endpoint"),
            protocol=protocol,  # type: ignore[arg-type]
            sample=sample,  # type: ignore[arg-type]
            emit_input=bool(raw.get("emit_input", False)),
            emit_output=bool(raw.get("emit_output", False)),
            service_name=str(raw.get("service_name", "bpg")),
        )


def _event_time_ns(event: BpgEvent) -> int | None:
    try:
        occurred_at = event.occurred_at
        if occurred_at.endswith("Z"):
            occurred_at = occurred_at[:-1] + "+00:00"
        return int(datetime.fromisoformat(occurred_at).timestamp() * 1_000_000_000)
    except Exception:  # noqa: BLE001
        return None


def _attribute_value(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    return canonical_json(value)


def _compact_attributes(attributes: Dict[str, Any]) -> Dict[str, Any]:
    return {k: _attribute_value(v) for k, v in attributes.items() if v is not None}


def _event_attributes(
    event: BpgEvent,
    *,
    emit_input: bool,
    emit_output: bool,
) -> Dict[str, Any]:
    payload = dict(event.payload or {})
    attributes: Dict[str, Any] = {
        "bpg.event_id": event.event_id,
        "bpg.event_type": event.event_type,
        "bpg.run_id": event.run_id,
        "bpg.process_name": event.process_name,
        "bpg.process_version": event.process_version,
        "bpg.process_hash": event.process_hash,
        "bpg.engine": event.engine_backend,
        "bpg.node_id": event.node_id,
        "bpg.node_type": event.node_type,
        "bpg.node_package": event.node_package,
        "bpg.provider_id": event.provider_id,
        "bpg.policy.id": event.policy_id,
        "bpg.audit.event_id": event.event_id,
        "bpg.temporal.namespace": event.temporal_namespace,
        "bpg.temporal.workflow_id": event.temporal_workflow_id,
        "bpg.temporal.run_id": event.temporal_run_id,
        "bpg.temporal.activity_id": event.temporal_activity_id,
        "bpg.temporal.activity_type": event.temporal_activity_type,
        "bpg.temporal.attempt": event.temporal_attempt,
        "bpg.temporal.task_queue": event.temporal_task_queue,
        "bpg.temporal.timer_id": event.temporal_timer_id,
        "bpg.temporal.signal_name": event.temporal_signal_name,
        "bpg.temporal.child_workflow_id": event.temporal_child_workflow_id,
        "bpg.provider_job_id": event.provider_job_id,
        "bpg.artifact.name": event.artifact_name,
        "bpg.artifact.sha256": event.artifact_sha256,
        "bpg.input.sha256": event.input_sha256,
        "bpg.output.sha256": event.output_sha256,
        "bpg.payload.sha256": event.payload_sha256,
        "bpg.retry.attempt": payload.get("attempt"),
        "bpg.retry.delay_seconds": payload.get("delay_seconds"),
        "bpg.policy.result": payload.get("result") or payload.get("status"),
        "bpg.status": payload.get("status"),
        "bpg.error_code": payload.get("error_code"),
    }
    if "error" in payload:
        attributes["bpg.error"] = payload["error"]
    if emit_input and "input" in payload:
        attributes["bpg.input"] = payload["input"]
    if emit_output and "output" in payload:
        attributes["bpg.output"] = payload["output"]
    for key, value in event.tags.items():
        attributes[f"bpg.tag.{key}"] = value
    return _compact_attributes(attributes)


class OpenTelemetryEventSink(EventSink):
    """Project canonical BPG events into OpenTelemetry traces and spans.

    A trace represents one BPG run. The root span represents the process run,
    and node lifecycle events create child spans. Other canonical event types
    are attached as span events to the relevant node span when possible and to
    the run span otherwise.
    """

    def __init__(
        self,
        *,
        config: TracingConfig | None = None,
        tracer_provider: Any | None = None,
        span_exporter: Any | None = None,
        span_processor: Any | None = None,
        tracer: Any | None = None,
    ) -> None:
        self._config = config or TracingConfig(enabled=True)
        self._run_spans: Dict[str, Any] = {}
        self._node_spans: Dict[tuple[str, str], Any] = {}
        self._provider = tracer_provider
        self._processor = span_processor
        self._logger = logging.getLogger("bpg.tracing")
        try:
            if tracer is not None:
                self._tracer = tracer
            else:
                self._tracer = self._build_tracer(
                    tracer_provider=tracer_provider,
                    span_exporter=span_exporter,
                    span_processor=span_processor,
                )
        except Exception as exc:  # noqa: BLE001
            self._tracer = None
            self._logger.warning("OpenTelemetry tracing disabled after setup failure: %s", exc)

    @classmethod
    def from_config(cls, config: Dict[str, Any] | TracingConfig | None) -> EventSink:
        tracing_config = (
            config if isinstance(config, TracingConfig) else TracingConfig.from_mapping(config)
        )
        if not tracing_config.enabled:
            return NoopEventSink()
        return cls(config=tracing_config)

    def _build_tracer(
        self,
        *,
        tracer_provider: Any | None,
        span_exporter: Any | None,
        span_processor: Any | None,
    ) -> Any:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor
        from opentelemetry.sdk.trace.sampling import ALWAYS_OFF, ALWAYS_ON

        provider = tracer_provider
        if provider is None:
            sampler = ALWAYS_OFF if self._config.sample == "never" else ALWAYS_ON
            provider = TracerProvider(
                sampler=sampler,
                resource=Resource.create({"service.name": self._config.service_name}),
            )
        self._provider = provider

        processor = span_processor
        if processor is None:
            exporter = span_exporter
            if exporter is None and self._config.exporter == "otlp":
                exporter = self._build_otlp_exporter()
            if exporter is not None:
                processor_cls = SimpleSpanProcessor if span_exporter is not None else BatchSpanProcessor
                processor = processor_cls(exporter)
        if processor is not None:
            provider.add_span_processor(processor)
        self._processor = processor
        return provider.get_tracer("bpg.runtime")

    def _build_otlp_exporter(self) -> Any:
        if self._config.protocol == "http/protobuf":
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        else:
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

        kwargs: Dict[str, Any] = {}
        if self._config.endpoint:
            kwargs["endpoint"] = self._config.endpoint
        return OTLPSpanExporter(**kwargs)

    def emit(self, event: BpgEvent) -> BpgEvent | None:
        if self._tracer is None:
            return None
        try:
            return self._emit(event)
        except Exception as exc:  # noqa: BLE001
            self._logger.warning("OpenTelemetry event export failed: %s", exc)
            return None

    def _emit(self, event: BpgEvent) -> BpgEvent | None:
        from opentelemetry.trace import Status, StatusCode

        attrs = _event_attributes(
            event,
            emit_input=self._config.emit_input,
            emit_output=self._config.emit_output,
        )
        timestamp = _event_time_ns(event)
        enriched: BpgEvent | None = None

        if event.event_type == "run_started":
            span = self._tracer.start_span(
                f"bpg.run {event.process_name}",
                attributes=attrs,
                start_time=timestamp,
            )
            self._run_spans[event.run_id] = span
            span.add_event(event.event_type, attrs, timestamp=timestamp)
            enriched = self._event_with_span_context(event, span)
            return enriched

        target_span = self._span_for_event(event, attrs, timestamp)
        if target_span is not None:
            target_span.add_event(event.event_type, attrs, timestamp=timestamp)
            if event.event_type in {"node_failed", "run_failed", "policy_blocked"}:
                target_span.set_status(Status(StatusCode.ERROR, str(attrs.get("bpg.error", ""))))
            elif event.event_type in {"node_completed", "run_completed"}:
                target_span.set_status(Status(StatusCode.OK))
            enriched = self._event_with_span_context(event, target_span)

        if event.event_type in {"node_completed", "node_failed", "node_skipped"} and event.node_id:
            span = self._node_spans.pop((event.run_id, event.node_id), None)
            if span is not None:
                span.end(end_time=timestamp)

        if event.event_type in {"run_completed", "run_failed"}:
            span = self._run_spans.pop(event.run_id, None)
            if span is not None:
                if event.event_type == "run_failed":
                    span.set_status(Status(StatusCode.ERROR))
                else:
                    span.set_status(Status(StatusCode.OK))
                span.end(end_time=timestamp)

        return enriched

    def _span_for_event(
        self,
        event: BpgEvent,
        attrs: Dict[str, Any],
        timestamp: int | None,
    ) -> Any | None:
        from opentelemetry import trace

        if event.node_id:
            key = (event.run_id, event.node_id)
            span = self._node_spans.get(key)
            if span is not None:
                return span
            if event.event_type == "node_started":
                parent_span = self._run_spans.get(event.run_id)
                context = trace.set_span_in_context(parent_span) if parent_span is not None else None
                span = self._tracer.start_span(
                    f"bpg.node {event.node_id}",
                    context=context,
                    attributes=attrs,
                    start_time=timestamp,
                )
                self._node_spans[key] = span
                return span
            if event.event_type in {"node_completed", "node_failed", "node_skipped"}:
                parent_span = self._run_spans.get(event.run_id)
                context = trace.set_span_in_context(parent_span) if parent_span is not None else None
                span = self._tracer.start_span(
                    f"bpg.node {event.node_id}",
                    context=context,
                    attributes=attrs,
                    start_time=timestamp,
                )
                self._node_spans[key] = span
                return span
        return self._run_spans.get(event.run_id)

    @staticmethod
    def _event_with_span_context(event: BpgEvent, span: Any) -> BpgEvent:
        context = span.get_span_context()
        kwargs: Dict[str, Any] = {
            "trace_id": f"{context.trace_id:032x}",
            "span_id": f"{context.span_id:016x}",
        }
        parent = getattr(span, "parent", None)
        if parent is not None:
            kwargs["parent_span_id"] = f"{parent.span_id:016x}"
        return event.model_copy(update=kwargs)

    def force_flush(self, timeout_millis: int = 30_000) -> bool:
        try:
            if self._provider is not None:
                return bool(self._provider.force_flush(timeout_millis=timeout_millis))
        except Exception:  # noqa: BLE001
            return False
        return True

    def shutdown(self) -> None:
        try:
            if self._provider is not None:
                self._provider.shutdown()
        except Exception:  # noqa: BLE001
            pass


def _observability_config_from_process(process: Any) -> Dict[str, Any] | None:
    """Extract observability sink configuration from a process definition."""
    observability = getattr(process, "observability", None)
    if observability is None:
        return None
    if hasattr(observability, "model_dump"):
        dumped = observability.model_dump(mode="json", exclude_none=True)
        if not dumped:
            return None
        return {"observability": dumped}
    if isinstance(observability, Mapping):
        if not observability:
            return None
        return {"observability": dict(observability)}
    return None


def build_runtime_event_sink(process: Any) -> EventSink:
    """Build the runtime observability sink from a process definition.

    Reads ``process.observability`` when present and delegates to
    :func:`build_observability_sink`. Returns :class:`NoopEventSink` when
    observability is unset or fully disabled.
    """
    config = _observability_config_from_process(process)
    if config is None:
        return NoopEventSink()
    return build_observability_sink(config)


def build_observability_sink(
    config: Dict[str, Any] | TracingConfig | None,
    *,
    extra_sinks: Iterable[EventSink] = (),
) -> EventSink:
    """Build the configured runtime observability sink group.

    Tracing is disabled by default. Extra sinks are appended after tracing so
    they can receive trace/span IDs when an OpenTelemetry sink is active.
    """
    tracing_sink = OpenTelemetryEventSink.from_config(config)
    if isinstance(config, TracingConfig):
        audit_sink = None
    else:
        from bpg.audit import PostgresAuditEventSink

        audit_sink = PostgresAuditEventSink.from_config(config)  # type: ignore[arg-type]
    sinks = [tracing_sink, audit_sink, *list(extra_sinks)]
    active_sinks = [
        sink for sink in sinks if sink is not None and not isinstance(sink, NoopEventSink)
    ]
    if not active_sinks:
        return NoopEventSink()
    if len(active_sinks) == 1:
        return active_sinks[0]
    return EventSinkGroup(active_sinks)


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
    for key in (
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
    ):
        value = getattr(event, key)
        if value is not None:
            legacy[key] = value  # type: ignore[typeddict-unknown-key]
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
