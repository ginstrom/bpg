"""Spec-level test runner for process behavior validation."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import load_yaml_file, parse_process_file
from bpg.compiler.validator import validate_process
from bpg.models.schema import NodeType
from bpg.providers.base import ExecutionContext
from bpg.runtime.orchestrator import BpgOrchestrator
from bpg.testing.models import SpecTestCase, SpecTestSuite


class _SpecTestNodeAdapter:
    def __init__(self, *, node_mocks: dict[str, dict[str, Any]]) -> None:
        self._node_mocks = node_mocks
        self._tasks: dict[str, tuple[str, dict[str, Any]]] = {}

    def start_node(
        self,
        *,
        node_name: str,
        node_type: NodeType,
        input_payload: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> str:
        _ = node_type
        _ = config
        _ = context
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = (node_name, dict(input_payload))
        return task_id

    def poll(self, task_id: str) -> tuple[str, Dict[str, Any] | None, Dict[str, Any] | None]:
        node_name, input_payload = self._tasks[task_id]
        if node_name in self._node_mocks:
            payload = self._node_mocks[node_name]
            if "__error__" in payload:
                return "failed", None, {"code": "mock_failure", "message": str(payload["__error__"])}
            return "completed", payload, None
        return "completed", input_payload, None

    def cancel(self, task_id: str) -> None:
        _ = task_id


def load_test_suite(path: Path) -> SpecTestSuite:
    raw = load_yaml_file(path)
    return SpecTestSuite.model_validate(raw)


def _evaluate_expectations(case: SpecTestCase, result: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    statuses: dict[str, str] = result.get("node_statuses", {})
    log_events = [entry.get("event") for entry in result.get("execution_log", [])]
    completed_nodes = {node for node, status in statuses.items() if status == "completed"}

    for node in case.expect.path_contains:
        if node not in completed_nodes:
            errors.append(f"path_contains missing node {node!r}")

    if case.expect.required_fields:
        process_output = result.get("process_output")
        if not isinstance(process_output, dict):
            errors.append("required_fields expectation needs dict process_output")
        else:
            for field in case.expect.required_fields:
                if field not in process_output:
                    errors.append(f"required output field missing: {field!r}")

    if case.expect.event_sequence:
        if log_events != case.expect.event_sequence:
            errors.append(
                f"event_sequence mismatch: expected={case.expect.event_sequence!r} got={log_events!r}"
            )
    return errors


def run_spec_test_suite(suite_path: Path) -> dict[str, Any]:
    suite = load_test_suite(suite_path)
    process_file = suite.resolve_process_file(suite_path)
    process = parse_process_file(process_file)
    validate_process(process)
    ir = compile_process(process)

    cases: list[dict[str, Any]] = []
    passed_count = 0
    for case in suite.tests:
        adapter = _SpecTestNodeAdapter(node_mocks=case.mocks)
        orchestrator = BpgOrchestrator(ir=ir, node_adapter=adapter)
        run_id = str(uuid.uuid4())
        result = orchestrator.run(input_payload=case.input, run_id=run_id)
        expectation_errors = _evaluate_expectations(case, result)
        passed = len(expectation_errors) == 0 and result.get("run_status") == "completed"
        if passed:
            passed_count += 1
        cases.append(
            {
                "name": case.name,
                "passed": passed,
                "run_status": result.get("run_status"),
                "errors": expectation_errors,
            }
        )

    return {
        "suite": str(suite_path),
        "process_file": str(process_file),
        "total": len(suite.tests),
        "passed": passed_count,
        "failed": len(suite.tests) - passed_count,
        "cases": cases,
    }
