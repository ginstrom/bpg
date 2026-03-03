from pathlib import Path

import pytest

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
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
    assert "langgraph" in available_backends()
    assert "local" in available_backends()
    assert get_backend("langgraph").name == "langgraph"
    assert get_backend("local").name == "local"


def test_unknown_backend_raises_clear_error():
    with pytest.raises(ValueError) as exc:
        get_backend("does-not-exist")
    assert "Unknown engine backend" in str(exc.value)


def test_same_process_runs_with_langgraph_and_local_backends(tmp_path: Path):
    process = _process(tmp_path)
    store = StateStore(tmp_path / "state")
    store.save_process(compile_process(process))

    mock = MockProvider()
    mock.set_default({"ok": True})
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock

    try:
        run_id_langgraph = Engine(
            process=process,
            state_store=store,
            backend="langgraph",
        ).trigger({})
        run_id_local = Engine(
            process=process,
            state_store=store,
            backend="local",
        ).trigger({})

        run_langgraph = store.load_run(run_id_langgraph)
        run_local = store.load_run(run_id_local)
        assert run_langgraph is not None
        assert run_local is not None
        assert run_langgraph["status"] == "completed"
        assert run_local["status"] == "completed"
        assert run_langgraph["output"] is True
        assert run_local["output"] is True
        assert run_langgraph["engine_backend"] == "langgraph"
        assert run_local["engine_backend"] == "local"
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock


def test_engine_trigger_rejects_unknown_backend(tmp_path: Path):
    process = _process(tmp_path)
    store = StateStore(tmp_path / "state")

    with pytest.raises(EngineError) as exc:
        Engine(process=process, state_store=store, backend="bad-backend").trigger({})
    assert "Unknown engine backend" in str(exc.value)


def test_local_backend_uses_polling_orchestrator_loop(tmp_path: Path):
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
        run_id = Engine(process=process, state_store=store, backend="local").trigger({"text": "hello"})
        run = store.load_run(run_id)
        assert run is not None
        assert run["status"] == "completed"
        assert run["output"] == "hello"

        records = store.list_node_records(run_id)
        assert records["worker"]["status"] == "completed"
        events = store.load_execution_log(run_id)
        event_names = [e.get("event") for e in events if e.get("node") == "worker"]
        assert "node_scheduled" in event_names
        assert "node_completed" in event_names
    finally:
        if previous is None:
            PROVIDER_REGISTRY.pop("custom.async_echo", None)
        else:
            PROVIDER_REGISTRY["custom.async_echo"] = previous
