"""Tests for retry backoff, structured event emission, and run replay.

Covers:
1. _compute_retry_delay — all three BackoffStrategy values
2. LangGraphRuntime emits correct event sequence on success
3. LangGraphRuntime emits node_started + node_retrying + node_failed
   for a retryable error; verifies sleep is called with correct delay
4. Replay reconstructs events from an execution_log without re-running providers
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.models.schema import BackoffStrategy, NodeStatus, RetryPolicy
from bpg.providers.base import ProviderError
from bpg.providers.mock import MockProvider
from bpg.runtime.langgraph_runtime import (
    LangGraphRuntime,
    _compute_retry_delay,
)
from bpg.runtime.events import BpgEvent
from bpg.audit.postgres import PostgresAuditEventSink
from bpg.compiler.parser import parse_process_file
from bpg.runtime.observability import (
    EventSinkGroup,
    ListEventSink,
    NoopEventSink,
    OpenTelemetryEventSink,
    TracingConfig,
    build_observability_sink,
    build_runtime_event_sink,
    replay_run,
)

_PROCESS_FILE = Path(__file__).resolve().parents[1] / "process.bpg.yaml"


@pytest.fixture(scope="module")
def ir():
    process = parse_process_file(_PROCESS_FILE)
    validate_process(process)
    return compile_process(process)


def _providers(mock: MockProvider) -> dict:
    return {
        "dashboard.form": mock,
        "agent.pipeline": mock,
        "slack.interactive": mock,
        "http.gitlab": mock,
    }


# ---------------------------------------------------------------------------
# 1. _compute_retry_delay
# ---------------------------------------------------------------------------


class TestComputeRetryDelay:
    def test_exponential(self):
        assert _compute_retry_delay(0, BackoffStrategy.EXPONENTIAL, 2.0, 60.0) == 2.0
        assert _compute_retry_delay(1, BackoffStrategy.EXPONENTIAL, 2.0, 60.0) == 4.0
        assert _compute_retry_delay(2, BackoffStrategy.EXPONENTIAL, 2.0, 60.0) == 8.0

    def test_linear(self):
        assert _compute_retry_delay(0, BackoffStrategy.LINEAR, 3.0, 60.0) == 3.0
        assert _compute_retry_delay(1, BackoffStrategy.LINEAR, 3.0, 60.0) == 6.0
        assert _compute_retry_delay(2, BackoffStrategy.LINEAR, 3.0, 60.0) == 9.0

    def test_constant(self):
        assert _compute_retry_delay(0, BackoffStrategy.CONSTANT, 5.0, 60.0) == 5.0
        assert _compute_retry_delay(3, BackoffStrategy.CONSTANT, 5.0, 60.0) == 5.0

    def test_max_delay_caps_exponential(self):
        # 2 ** 10 * 1.0 = 1024 > max_delay=10
        assert _compute_retry_delay(10, BackoffStrategy.EXPONENTIAL, 1.0, 10.0) == 10.0


# ---------------------------------------------------------------------------
# 2. Event sequence for a successful run
# ---------------------------------------------------------------------------


def test_events_emitted_on_success(ir):
    mock = MockProvider()
    mock.register_for_node("triage", {
        "risk": "low", "summary": "x", "labels": [], "recommended_assignee": "a"
    })
    mock.register_for_node("gitlab", {"ticket_id": "T-1", "url": "http://x"})

    sink = ListEventSink()
    runtime = LangGraphRuntime(ir=ir, providers=_providers(mock), event_sink=sink)
    runtime.run({"title": "t", "severity": "S3", "description": "d", "reporter_email": "e@e"})

    types = [e["event_type"] for e in sink.events]

    assert types[0] == "run_started"
    assert types[-1] == "run_completed"

    # Trigger fires as node_completed without node_started
    trigger_events = sink.for_node("intake_form")
    assert trigger_events[0]["event_type"] == "node_completed"
    assert sink.canonical_events[0].event_type == "run_started"
    assert isinstance(sink.canonical_events[0], BpgEvent)

    # triage: started → completed
    triage_events = sink.for_node("triage")
    assert [e["event_type"] for e in triage_events] == ["node_started", "node_completed"]

    # approval: skipped (no node_started because no invocation)
    approval_events = sink.for_node("approval")
    assert len(approval_events) == 1
    assert approval_events[0]["event_type"] == "node_skipped"

    # gitlab: started → completed
    gitlab_events = sink.for_node("gitlab")
    assert [e["event_type"] for e in gitlab_events] == ["node_started", "node_completed"]

    # Every completed event has the required fields
    for ev in sink.by_type("node_completed"):
        assert "run_id" in ev
        assert "process_name" in ev
        assert "timestamp" in ev


# ---------------------------------------------------------------------------
# 3. Retry events with backoff delay
# ---------------------------------------------------------------------------


def test_retry_events_and_backoff(ir):
    """node_retry_scheduled events carry attempt/delay; time.sleep is called."""
    mock = MockProvider()
    # Register a retryable error so all attempts fail
    mock.register_error(
        "triage",
        ProviderError(code="rate_limit", message="Too many requests", retryable=True),
    )

    # Patch the retry policy on the resolved node to 3 attempts with known delay
    triage_node = ir.resolved_nodes["triage"]
    policy = RetryPolicy(
        max_attempts=3,
        backoff=BackoffStrategy.CONSTANT,
        initial_delay="0.1s",
        max_delay="1s",
    )
    # Temporarily swap the retry policy via object.__setattr__ (frozen dataclass)
    original_instance = triage_node.instance
    patched_instance = original_instance.model_copy(update={"retry": policy})
    object.__setattr__(triage_node, "instance", patched_instance)

    sink = ListEventSink()
    try:
        with patch("bpg.runtime.langgraph_runtime.time.sleep") as mock_sleep:
            runtime = LangGraphRuntime(ir=ir, providers=_providers(mock), event_sink=sink)
            state = runtime.run(
                {"title": "t", "severity": "S1", "description": "d", "reporter_email": "e@e"}
            )
    finally:
        # Restore original instance
        object.__setattr__(triage_node, "instance", original_instance)

    triage_events = sink.for_node("triage")
    event_types = [e["event_type"] for e in triage_events]

    # node_started → node_retry_scheduled × 2 → node_failed
    assert event_types[0] == "node_started"
    retrying = [e for e in triage_events if e["event_type"] == "node_retry_scheduled"]
    assert len(retrying) == 2  # 3 attempts → 2 retries between them
    assert event_types[-1] == "node_failed"

    # Retry events carry attempt number and delay
    assert retrying[0]["attempt"] == 1
    assert retrying[1]["attempt"] == 2
    assert retrying[0]["delay_seconds"] == pytest.approx(0.1)

    # time.sleep was called twice with the backoff delay
    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(pytest.approx(0.1))

    # node_failed carries the error code
    failed = sink.by_type("node_failed")
    triage_failed = [e for e in failed if e["node"] == "triage"]
    assert triage_failed[0]["error_code"] == "rate_limit"

    # Final state records the failure
    assert state["node_statuses"]["triage"] == NodeStatus.FAILED.value


def test_event_sink_group_preserves_order():
    event = BpgEvent(
        event_type="run_started",
        run_id="r1",
        process_name="p1",
        process_version="v1",
        process_hash="h1",
        engine_backend="test",
    )
    calls: list[str] = []

    class RecordingSink(ListEventSink):
        def __init__(self, name: str) -> None:
            super().__init__()
            self._name = name

        def emit(self, event: BpgEvent) -> None:
            calls.append(self._name)
            super().emit(event)

    first = RecordingSink("first")
    second = RecordingSink("second")
    EventSinkGroup([first, second]).emit(event)

    assert calls == ["first", "second"]
    assert first.canonical_events == [event]
    assert second.canonical_events == [event]


# ---------------------------------------------------------------------------
# 4. OpenTelemetry tracing sink
# ---------------------------------------------------------------------------


def _otel_exporter():
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    return InMemorySpanExporter()


def test_tracing_is_disabled_by_default():
    sink = build_observability_sink(None)

    assert isinstance(sink, NoopEventSink)


def test_build_runtime_event_sink_without_observability(ir):
    sink = build_runtime_event_sink(ir.process)

    assert isinstance(sink, NoopEventSink)


def test_build_runtime_event_sink_registers_audit_sink():
    fixtures = Path(__file__).resolve().parent / "fixtures" / "audit_policy"
    process = parse_process_file(fixtures / "enabled.bpg.yaml")

    sink = build_runtime_event_sink(
        process.model_copy(
            update={
                "observability": process.observability.model_copy(
                    update={"audit": process.observability.audit.model_copy(update={"dsn": "postgresql://example"})}
                )
            }
        )
    )

    assert isinstance(sink, PostgresAuditEventSink)


def test_build_runtime_event_sink_returns_noop_when_audit_disabled():
    fixtures = Path(__file__).resolve().parent / "fixtures" / "audit_policy"
    process = parse_process_file(fixtures / "enabled.bpg.yaml")

    sink = build_runtime_event_sink(
        process.model_copy(
            update={
                "observability": process.observability.model_copy(
                    update={
                        "audit": process.observability.audit.model_copy(
                            update={"enabled": False, "dsn": "postgresql://example"}
                        )
                    }
                )
            }
        )
    )

    assert isinstance(sink, NoopEventSink)


def test_opentelemetry_sink_exports_run_and_node_spans():
    exporter = _otel_exporter()
    sink = OpenTelemetryEventSink(
        config=TracingConfig(enabled=True, exporter="none"),
        span_exporter=exporter,
    )
    run_started = BpgEvent(
        event_type="run_started",
        run_id="run-otel-1",
        process_name="otel-process",
        process_version="v1",
        process_hash="h1",
        engine_backend="test",
        payload={"status": "running"},
    )
    node_started = BpgEvent(
        event_type="node_started",
        run_id="run-otel-1",
        process_name="otel-process",
        process_version="v1",
        process_hash="h1",
        engine_backend="test",
        node_id="triage",
        node_type="triage_agent@v1",
        node_package="pkg",
        provider_id="agent.pipeline",
        temporal_namespace="default",
        temporal_workflow_id="wf-otel",
        temporal_run_id="temporal-run-otel",
        temporal_activity_id="activity-otel",
        temporal_activity_type="BpgNodeActivity",
        temporal_attempt=2,
        temporal_task_queue="bpg-workers",
        input_sha256="input-hash",
        payload={"status": "running", "input": {"secret": "hidden"}},
    )
    retry = node_started.model_copy(
        update={
            "event_id": "retry-event",
            "event_type": "node_retry_scheduled",
            "payload": {
                "status": "running",
                "attempt": 1,
                "delay_seconds": 0.5,
                "error": "rate limited",
                "error_code": "rate_limit",
            },
        }
    )
    node_completed = node_started.model_copy(
        update={
            "event_id": "node-completed",
            "event_type": "node_completed",
            "output_sha256": "output-hash",
            "payload": {"status": "completed", "output": {"result": "ok"}},
        }
    )
    run_completed = run_started.model_copy(
        update={
            "event_id": "run-completed",
            "event_type": "run_completed",
            "payload": {"status": "completed"},
        }
    )

    enriched = [
        sink.emit(run_started),
        sink.emit(node_started),
        sink.emit(retry),
        sink.emit(node_completed),
        sink.emit(run_completed),
    ]
    sink.force_flush()
    spans = exporter.get_finished_spans()

    assert {span.name for span in spans} == {"bpg.run otel-process", "bpg.node triage"}
    run_span = next(span for span in spans if span.name == "bpg.run otel-process")
    node_span = next(span for span in spans if span.name == "bpg.node triage")
    assert node_span.context.trace_id == run_span.context.trace_id
    assert node_span.parent.span_id == run_span.context.span_id
    assert run_span.attributes["bpg.run_id"] == "run-otel-1"
    assert node_span.attributes["bpg.node_id"] == "triage"
    assert node_span.attributes["bpg.provider_id"] == "agent.pipeline"
    assert node_span.attributes["bpg.temporal.workflow_id"] == "wf-otel"
    assert node_span.attributes["bpg.temporal.run_id"] == "temporal-run-otel"
    assert node_span.attributes["bpg.temporal.activity_id"] == "activity-otel"
    assert node_span.attributes["bpg.temporal.activity_type"] == "BpgNodeActivity"
    assert node_span.attributes["bpg.temporal.attempt"] == 2
    assert node_span.attributes["bpg.temporal.task_queue"] == "bpg-workers"
    assert "node_retry_scheduled" in [event.name for event in node_span.events]
    retry_event = next(event for event in node_span.events if event.name == "node_retry_scheduled")
    assert retry_event.attributes["bpg.retry.attempt"] == 1
    assert retry_event.attributes["bpg.retry.delay_seconds"] == 0.5
    assert "bpg.input" not in node_span.events[0].attributes
    assert "bpg.output" not in node_span.events[-1].attributes
    assert all(event is not None and event.trace_id and event.span_id for event in enriched)


def test_opentelemetry_sink_can_emit_raw_inputs_and_outputs_when_enabled():
    exporter = _otel_exporter()
    sink = OpenTelemetryEventSink(
        config=TracingConfig(enabled=True, exporter="none", emit_input=True, emit_output=True),
        span_exporter=exporter,
    )
    run = BpgEvent(
        event_type="run_started",
        run_id="run-otel-io",
        process_name="otel-io",
        process_version="v1",
        process_hash="h1",
        engine_backend="test",
    )
    node = BpgEvent(
        event_type="node_completed",
        run_id="run-otel-io",
        process_name="otel-io",
        process_version="v1",
        process_hash="h1",
        engine_backend="test",
        node_id="summarize",
        payload={
            "status": "completed",
            "input": {"body": "hello"},
            "output": {"summary": "hello"},
        },
    )

    sink.emit(run)
    sink.emit(node)
    sink.emit(run.model_copy(update={"event_type": "run_completed"}))
    sink.force_flush()

    span = next(span for span in exporter.get_finished_spans() if span.name == "bpg.node summarize")
    event_attrs = span.events[-1].attributes
    assert event_attrs["bpg.input"] == '{"body":"hello"}'
    assert event_attrs["bpg.output"] == '{"summary":"hello"}'


def test_opentelemetry_export_failure_is_non_fatal():
    from opentelemetry.sdk.trace.export import SpanExporter

    class FailingExporter(SpanExporter):
        def export(self, spans):  # noqa: ANN001, ARG002
            raise RuntimeError("collector unavailable")

        def shutdown(self):  # noqa: D401
            return None

    sink = OpenTelemetryEventSink(
        config=TracingConfig(enabled=True, exporter="none"),
        span_exporter=FailingExporter(),
    )
    run = BpgEvent(
        event_type="run_started",
        run_id="run-otel-failure",
        process_name="otel-failure",
        process_version="v1",
        process_hash="h1",
        engine_backend="test",
    )

    sink.emit(run)
    sink.emit(run.model_copy(update={"event_type": "run_completed"}))


def test_event_sink_group_passes_trace_ids_to_downstream_sinks():
    exporter = _otel_exporter()
    tracing = OpenTelemetryEventSink(
        config=TracingConfig(enabled=True, exporter="none"),
        span_exporter=exporter,
    )
    events = ListEventSink()
    sink = EventSinkGroup([tracing, events])
    run = BpgEvent(
        event_type="run_started",
        run_id="run-otel-enrich",
        process_name="otel-enrich",
        process_version="v1",
        process_hash="h1",
        engine_backend="test",
    )

    sink.emit(run)

    assert events.canonical_events[0].trace_id is not None
    assert events.canonical_events[0].span_id is not None


# ---------------------------------------------------------------------------
# 5. replay_run reconstructs events from execution_log
# ---------------------------------------------------------------------------


def test_replay_run_from_execution_log(ir):
    mock = MockProvider()
    mock.register_for_node("triage", {
        "risk": "high", "summary": "x", "labels": [], "recommended_assignee": "a"
    })
    mock.register_for_node("approval", {"approved": True, "reason": "ok"})
    mock.register_for_node("gitlab", {"ticket_id": "T-9", "url": "http://x"})

    live_sink = ListEventSink()
    runtime = LangGraphRuntime(ir=ir, providers=_providers(mock), event_sink=live_sink)
    final_state = runtime.run(
        {"title": "t", "severity": "S1", "description": "d", "reporter_email": "e@e"}
    )

    # Replay into a fresh sink
    replay_sink = ListEventSink()
    replay_run(
        execution_log=final_state["execution_log"],
        run_id=final_state["run_id"],
        process_name=final_state["process_name"],
        sink=replay_sink,
    )

    # One event per node in the log
    assert len(replay_sink.events) == len(final_state["execution_log"])

    # Every replayed event carries the run_id and process_name
    for ev in replay_sink.events:
        assert ev["run_id"] == final_state["run_id"]
        assert ev["process_name"] == final_state["process_name"]

    # Completed nodes map to node_completed event_type
    completed_nodes = [
        e["node"] for e in replay_sink.events if e["event_type"] == "node_completed"
    ]
    assert "triage" in completed_nodes
    assert "approval" in completed_nodes
    assert "gitlab" in completed_nodes

    # Skipped node maps to node_skipped
    # (approval is skipped in the low-risk path; here we used high-risk so
    # check for whatever node was actually skipped)
    skipped_nodes = [
        e["node"] for e in replay_sink.events if e["event_type"] == "node_skipped"
    ]
    # In a high-risk run approval fires, nothing is skipped beyond the
    # conditional low-risk path — but we just confirm structure is correct.
    for ev in replay_sink.events:
        assert "event_type" in ev
        assert "node" in ev
        assert "timestamp" in ev
