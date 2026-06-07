import builtins
from pathlib import Path
from unittest.mock import patch

import pytest

from bpg_temporal import LEGACY_RUNTIME_MODULE, TemporalRuntime
from bpg.audit import AuditSinkFailure
from bpg.audit.postgres import PostgresAuditEventSink
from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.models.schema import RuntimeTracingPolicy
from bpg.engines.langgraph.backend import LangGraphExecutionBackend
from bpg.providers import PROVIDER_REGISTRY
from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
)
from bpg.providers.mock import MockProvider
from bpg.runtime.backends import available_backends, get_backend
from bpg.runtime.engine import Engine, EngineError
from bpg.runtime.events import BpgEvent
from bpg.runtime.observability import (
    EventSinkGroup,
    ListEventSink,
    NoopEventSink,
    OpenTelemetryEventSink,
    TracingConfig,
    build_runtime_event_sink,
)
from bpg.state.store import StateStore


def _process(tmp_path: Path):
    path = tmp_path / "process.bpg.yaml"
    path.write_text(
        """
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


def test_backend_registry_reports_known_backends():
    assert available_backends() == ["temporal"]
    assert get_backend("temporal").name == "temporal"
    assert get_backend("local").name == "temporal"
    assert get_backend("langgraph").name == "temporal"


def test_temporal_package_exposes_runtime_bridge():
    runtime = TemporalRuntime()
    assert runtime.backend_name == "temporal"
    assert LEGACY_RUNTIME_MODULE == "bpg.runtime.engine"


def test_unknown_backend_raises_clear_error():
    with pytest.raises(ValueError) as exc:
        get_backend("does-not-exist")
    assert "Unknown engine backend" in str(exc.value)


def test_temporal_factory_reraises_nested_import_errors(monkeypatch: pytest.MonkeyPatch):
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "bpg_temporal":
            raise ModuleNotFoundError("No module named 'transitive_dep'", name="transitive_dep")
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", _fake_import)

    with pytest.raises(ModuleNotFoundError) as exc:
        get_backend("temporal")
    assert exc.value.name == "transitive_dep"


def test_same_process_runs_with_temporal_backend(tmp_path: Path):
    process = _process(tmp_path)
    store = StateStore(tmp_path / "state")
    store.save_process(compile_process(process))

    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock

    try:
        run_id = Engine(
            process=process,
            state_store=store,
            backend="temporal",
        ).trigger({})

        run = store.load_run(run_id)
        assert run is not None
        assert run["status"] == "completed"
        assert run["output"] is True
        assert run["engine_backend"] == "temporal"
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock


def test_temporal_fallback_backend_preserves_cached_results(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    process = _process(tmp_path)
    store = StateStore(tmp_path / "state")
    store.save_process(compile_process(process))

    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    real_import = builtins.__import__

    def _fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name == "bpg_temporal":
            raise ModuleNotFoundError("No module named 'bpg_temporal'", name="bpg_temporal")
        return real_import(name, globals, locals, fromlist, level)

    try:
        engine = Engine(process=process, state_store=store, backend="temporal")
        run_id = engine.trigger({})
        initial_calls = len(mock.calls)
        assert initial_calls >= 1

        store.update_run(run_id, {"status": "running"})
        monkeypatch.setattr(builtins, "__import__", _fake_import)

        engine.step(run_id)
        assert len(mock.calls) == initial_calls
        run = store.load_run(run_id)
        assert run is not None
        assert run["status"] == "completed"
        assert run["engine_backend"] == "temporal"
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock


def test_temporal_runtime_raises_required_provider_init_errors(tmp_path: Path):
    process = _process(tmp_path)
    previous_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: (_ for _ in ()).throw(RuntimeError("missing MOCK_API_KEY"))

    try:
        with pytest.raises(RuntimeError) as exc:
            TemporalRuntime().build_workflow(process=process)
        assert "Failed to initialize provider(s) required by the process" in str(exc.value)
        assert "mock" in str(exc.value)
        assert "missing MOCK_API_KEY" in str(exc.value)
    finally:
        PROVIDER_REGISTRY["mock"] = previous_mock


def test_engine_trigger_rejects_unknown_backend(tmp_path: Path):
    process = _process(tmp_path)
    store = StateStore(tmp_path / "state")

    with pytest.raises(EngineError) as exc:
        Engine(process=process, state_store=store, backend="bad-backend").trigger({})
    assert "Unknown engine backend" in str(exc.value)


def _audit_enabled_process(tmp_path: Path, *, failure_policy: str = "warn"):
    path = tmp_path / "audit-process.bpg.yaml"
    path.write_text(
        f"""
metadata:
  name: audit-enabled
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
    config_schema: {{}}
  work_node@v1:
    in: object
    out: Out
    provider: mock
    version: v1
    config_schema: {{}}
nodes:
  start:
    type: start_node@v1
    config: {{}}
  work:
    type: work_node@v1
    config: {{}}
trigger: start
output: work.out.ok
edges:
  - from: start
    to: work
observability:
  audit:
    enabled: true
    sink: postgres
    dsn: postgresql://example
    failure_policy: {failure_policy}
"""
    )
    process = parse_process_file(path)
    validate_process(process)
    return process


class _RecordingAuditSink(PostgresAuditEventSink):
    def __init__(self) -> None:
        super().__init__(dsn="postgresql://example", failure_policy="warn")
        self.events: list[BpgEvent] = []

    def insert_event(self, event: BpgEvent):  # type: ignore[override]
        self.events.append(event)
        return None


class _FailingAuditSink(PostgresAuditEventSink):
    def insert_event(self, event: BpgEvent):  # type: ignore[override]
        raise RuntimeError("database unavailable")


def test_langgraph_backend_wires_runtime_event_sink(tmp_path: Path):
    process = _audit_enabled_process(tmp_path)
    store = StateStore(tmp_path / "state")
    store.save_process(compile_process(process))

    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    audit_sink = _RecordingAuditSink()

    try:
        with patch(
            "bpg.engines.langgraph.backend.build_runtime_event_sink",
            return_value=audit_sink,
        ):
            final_state = LangGraphExecutionBackend().run(
                process=process,
                state_store=store,
                run_id="run-audit-1",
                input_payload={},
                cached_results={},
            )

        assert final_state["run_status"] == "completed"
        assert {event.event_type for event in audit_sink.events} >= {
            "run_started",
            "run_completed",
            "node_completed",
        }
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock


def test_temporal_workflow_wires_runtime_event_sink(tmp_path: Path):
    process = _audit_enabled_process(tmp_path)
    audit_sink = _RecordingAuditSink()

    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock

    try:
        with patch(
            "bpg_temporal.runtime.build_runtime_event_sink",
            return_value=audit_sink,
        ):
            result = TemporalRuntime().run_workflow(
                process=process,
                input_payload={},
                run_id="run-audit-2",
                cached_results={},
            )

        assert result["run_status"] == "completed"
        assert audit_sink.events
        assert audit_sink.events[0].event_type == "run_started"
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock


def test_runtime_sink_fail_run_aborts_backend_execution(tmp_path: Path):
    process = _audit_enabled_process(tmp_path, failure_policy="fail_run")
    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    failing_sink = _FailingAuditSink(dsn="postgresql://example", failure_policy="fail_run")

    try:
        with patch(
            "bpg.engines.langgraph.backend.build_runtime_event_sink",
            return_value=failing_sink,
        ):
            with pytest.raises(AuditSinkFailure, match="Postgres audit event insert failed"):
                LangGraphExecutionBackend().run(
                    process=process,
                    state_store=StateStore(tmp_path / "state"),
                    run_id="run-audit-fail",
                    input_payload={},
                    cached_results={},
                )
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock


def test_runtime_sink_tracing_failure_does_not_abort_backend_execution(tmp_path: Path):
    process = _audit_enabled_process(tmp_path)
    process = process.model_copy(
        update={
            "observability": process.observability.model_copy(
                update={
                    "tracing": RuntimeTracingPolicy(enabled=True, exporter="none"),
                }
            )
        }
    )
    from opentelemetry.sdk.trace.export import SpanExporter

    class FailingExporter(SpanExporter):
        def export(self, spans):  # noqa: ANN001, ARG002
            raise RuntimeError("collector unavailable")

        def shutdown(self):  # noqa: D401
            return None

    tracing_sink = OpenTelemetryEventSink(
        config=TracingConfig(enabled=True, exporter="none"),
        span_exporter=FailingExporter(),
    )
    audit_sink = _RecordingAuditSink()
    sink = EventSinkGroup([tracing_sink, audit_sink])

    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock

    try:
        with patch(
            "bpg.engines.langgraph.backend.build_runtime_event_sink",
            return_value=sink,
        ):
            final_state = LangGraphExecutionBackend().run(
                process=process,
                state_store=StateStore(tmp_path / "state"),
                run_id="run-audit-tracing",
                input_payload={},
                cached_results={},
            )

        assert final_state["run_status"] == "completed"
        assert audit_sink.events
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock


def test_runtime_sink_disabled_audit_uses_noop_backend_path(tmp_path: Path):
    process = _audit_enabled_process(tmp_path)
    process = process.model_copy(
        update={
            "observability": process.observability.model_copy(
                update={
                    "audit": process.observability.audit.model_copy(update={"enabled": False})
                }
            )
        }
    )

    sink = build_runtime_event_sink(process)
    assert isinstance(sink, NoopEventSink)

    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock

    try:
        final_state = LangGraphExecutionBackend().run(
            process=process,
            state_store=StateStore(tmp_path / "state"),
            run_id="run-audit-disabled",
            input_payload={},
            cached_results={},
        )
        assert final_state["run_status"] == "completed"
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock


def test_temporal_backend_uses_polling_orchestrator_loop(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
metadata:
  name: async-local
  version: 1.0.0
types:
  In:
    text: string
  Out:
    text: string
node_types:
  trigger@v1:
    in: In
    out: In
    provider: core.passthrough
    version: v1
    config_schema: {}
  async_echo@v1:
    in: In
    out: Out
    provider: custom.async_echo
    version: v1
    config_schema: {}
nodes:
  start:
    type: trigger@v1
    config: {}
  worker:
    type: async_echo@v1
    config: {}
trigger: start
output: worker.out.text
edges:
  - from: start
    to: worker
    with:
      text: start.out.text
"""
    )
    process = parse_process_file(process_file)
    validate_process(process)
    store = StateStore(tmp_path / "state")
    store.save_process(compile_process(process))

    class _AsyncEchoProvider(Provider):
        provider_id = "custom.async_echo"

        def __init__(self) -> None:
            self._status_by_handle: dict[str, ExecutionStatus] = {}

        def invoke(self, input, config, context: ExecutionContext):
            _ = config
            handle = ExecutionHandle(
                handle_id=context.idempotency_key,
                idempotency_key=context.idempotency_key,
                provider_id=self.provider_id,
                provider_data={"output": {"text": input.get("text", "")}},
            )
            self._status_by_handle[handle.handle_id] = ExecutionStatus.RUNNING
            return handle

        def poll(self, handle):
            current = self._status_by_handle.get(handle.handle_id, ExecutionStatus.COMPLETED)
            if current == ExecutionStatus.RUNNING:
                self._status_by_handle[handle.handle_id] = ExecutionStatus.COMPLETED
                return ExecutionStatus.RUNNING
            return ExecutionStatus.COMPLETED

        def await_result(self, handle, timeout=None):
            _ = timeout
            return dict(handle.provider_data["output"])

        def cancel(self, handle):
            self._status_by_handle[handle.handle_id] = ExecutionStatus.FAILED

    previous = PROVIDER_REGISTRY.get("custom.async_echo")
    PROVIDER_REGISTRY["custom.async_echo"] = _AsyncEchoProvider
    try:
        run_id = Engine(process=process, state_store=store, backend="temporal").trigger({"text": "hello"})
        run = store.load_run(run_id)
        assert run is not None
        assert run["status"] == "completed"
        assert run["output"] == "hello"

        records = store.list_node_records(run_id)
        assert records["worker"]["status"] == "completed"
        events = store.load_execution_log(run_id)
        event_types = [e.get("event_type") for e in events if e.get("node") == "worker"]
        assert "node_completed" in event_types
    finally:
        if previous is None:
            PROVIDER_REGISTRY.pop("custom.async_echo", None)
        else:
            PROVIDER_REGISTRY["custom.async_echo"] = previous
