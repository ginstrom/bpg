from pathlib import Path

import pytest

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.providers import PROVIDER_REGISTRY
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
