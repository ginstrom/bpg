from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Protocol

from bpg.compiler.ir import ExecutionIR, ResolvedEdge
from bpg.compiler.validator import ResolvedTypeDef
from bpg.models.schema import NodeType
from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
    ProviderError,
    compute_idempotency_key,
)
from bpg.runtime.expr import eval_when, resolve_mapping
from bpg.runtime.state import RunState

_DURATION_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*(ms|s|m|h|d)$")
_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


class OrchestratorError(Exception):
    """Raised when orchestrator execution cannot proceed safely."""


class _RuntimeValidationError(Exception):
    pass


class NodeExecutionAdapter(Protocol):
    """Engine adapter that executes individual node tasks."""

    def start_node(
        self,
        *,
        node_name: str,
        node_type: NodeType,
        input_payload: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> str:
        ...

    def poll(self, task_id: str) -> tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        ...

    def cancel(self, task_id: str) -> None:
        ...


class ProviderNodeExecutionAdapter:
    """Node execution adapter backed by Provider invoke/poll/await_result."""

    def __init__(self, providers: Dict[str, Provider]) -> None:
        self._providers = providers
        self._tasks: Dict[str, tuple[Provider, ExecutionHandle]] = {}

    def start_node(
        self,
        *,
        node_name: str,
        node_type: NodeType,
        input_payload: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> str:
        provider = self._providers.get(node_type.provider)
        if provider is None:
            raise OrchestratorError(
                f"No provider registered for node {node_name!r} (provider={node_type.provider!r})"
            )
        handle = provider.invoke(input_payload, config, context)
        task_id = str(uuid.uuid4())
        self._tasks[task_id] = (provider, handle)
        return task_id

    def poll(self, task_id: str) -> tuple[str, Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        provider, handle = self._tasks[task_id]
        try:
            status = provider.poll(handle)
            if status == ExecutionStatus.RUNNING:
                return "running", None, None
            if status == ExecutionStatus.COMPLETED:
                output = provider.await_result(handle)
                return "completed", output, None
            try:
                provider.await_result(handle)
            except ProviderError as exc:
                return "failed", None, {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                }
            except Exception as exc:  # pragma: no cover
                return "failed", None, {"code": "provider_failed", "message": str(exc)}
            return "failed", None, {"code": "provider_failed", "message": "Provider reported failed status"}
        except ProviderError as exc:
            return "failed", None, {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
            }

    def cancel(self, task_id: str) -> None:
        provider, handle = self._tasks.get(task_id, (None, None))  # type: ignore[assignment]
        if provider is None or handle is None:
            return
        provider.cancel(handle)


@dataclass
class _InflightTask:
    task_id: str
    node_name: str
    node_input: Dict[str, Any]
    idempotency_key: str
    started_at: str
    deadline_monotonic: Optional[float]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_duration_seconds(value: Any) -> Optional[float]:
    if not isinstance(value, str) or not value.strip():
        return None
    match = _DURATION_RE.match(value.strip())
    if not match:
        return None
    return float(match.group(1)) * _DURATION_UNITS[match.group(2)]


def _validate_payload(payload: Dict[str, Any], resolved_type: ResolvedTypeDef, context: str) -> None:
    if not resolved_type.fields:
        return

    fields = resolved_type.fields
    missing = [
        name for name, field_type in fields.items()
        if field_type.is_required and (name not in payload or payload[name] is None)
    ]
    if missing:
        raise _RuntimeValidationError(
            f"{context}: missing required fields {sorted(missing)} (type={resolved_type.name!r})"
        )

    extra = sorted(set(payload.keys()) - set(fields.keys()))
    if extra:
        raise _RuntimeValidationError(
            f"{context}: unexpected fields {extra} not in type {resolved_type.name!r}"
        )


class BpgOrchestrator:
    """Engine-neutral orchestrator loop for process execution."""

    _TERMINAL_STATUSES = frozenset({"completed", "skipped", "failed", "timed_out"})

    def __init__(self, *, ir: ExecutionIR, node_adapter: NodeExecutionAdapter) -> None:
        self._ir = ir
        self._node_adapter = node_adapter
        self._incoming: Dict[str, list[ResolvedEdge]] = {name: [] for name in ir.resolved_nodes}
        for edge in ir.resolved_edges:
            self._incoming[edge.target.name].append(edge)

    def run(self, *, input_payload: Dict[str, Any], run_id: str) -> Dict[str, Any]:
        state: RunState = {
            "run_id": run_id,
            "process_name": self._ir.process.metadata.name if self._ir.process.metadata else "default",
            "trigger_input": dict(input_payload),
            "node_outputs": {},
            "node_statuses": {},
            "execution_log": [],
            "failure_routes": {},
            "recoverable_failures": [],
            "run_status": "running",
        }

        pending = set(self._ir.topological_order)
        inflight: Dict[str, _InflightTask] = {}

        while pending or inflight:
            progressed = False

            for node_name in self._ir.topological_order:
                if node_name not in pending:
                    continue

                maybe_task = self._schedule_if_ready(node_name=node_name, state=state, run_id=run_id)
                if maybe_task is None:
                    continue

                pending.remove(node_name)
                progressed = True
                if maybe_task.task_id:
                    inflight[node_name] = maybe_task

            if state["run_status"] == "failed":
                break

            now = time.monotonic()
            for node_name, task in list(inflight.items()):
                if task.deadline_monotonic is not None and now >= task.deadline_monotonic:
                    self._node_adapter.cancel(task.task_id)
                    record = {
                        "event": "node_failed",
                        "node": node_name,
                        "status": "timed_out",
                        "input": task.node_input,
                        "error": {"code": "timeout", "message": "Node execution timed out"},
                        "idempotency_key": task.idempotency_key,
                        "started_at": task.started_at,
                        "completed_at": _now_iso(),
                    }
                    state["execution_log"].append(record)
                    state["node_statuses"][node_name] = "timed_out"
                    inflight.pop(node_name, None)
                    state["run_status"] = "failed"
                    progressed = True
                    continue

                status, output, error = self._node_adapter.poll(task.task_id)
                if status == "running":
                    continue

                inflight.pop(node_name, None)
                progressed = True

                if status == "completed":
                    output_payload = output or {}
                    node = self._ir.resolved_nodes[node_name]
                    _validate_payload(output_payload, node.out_type, f"{node_name}.out")
                    state["node_outputs"][node_name] = output_payload
                    state["node_statuses"][node_name] = "completed"
                    state["execution_log"].append(
                        {
                            "event": "node_completed",
                            "node": node_name,
                            "status": "completed",
                            "input": task.node_input,
                            "output": output_payload,
                            "idempotency_key": task.idempotency_key,
                            "started_at": task.started_at,
                            "completed_at": _now_iso(),
                        }
                    )
                else:
                    state["node_statuses"][node_name] = "failed"
                    state["execution_log"].append(
                        {
                            "event": "node_failed",
                            "node": node_name,
                            "status": "failed",
                            "input": task.node_input,
                            "error": error or {"code": "provider_failed", "message": "Node execution failed"},
                            "idempotency_key": task.idempotency_key,
                            "started_at": task.started_at,
                            "completed_at": _now_iso(),
                        }
                    )
                    state["run_status"] = "failed"

            if not progressed:
                if inflight:
                    time.sleep(0.05)
                    continue
                break

        if state["run_status"] != "failed":
            state["run_status"] = "completed"

        final_state: Dict[str, Any] = {
            "run_status": state["run_status"],
            "execution_log": state["execution_log"],
            "node_outputs": state["node_outputs"],
            "node_statuses": state["node_statuses"],
        }

        output_ref = self._ir.process.output
        if output_ref and state["run_status"] == "completed":
            process_output = resolve_mapping({"_": output_ref}, state, self._ir.trigger.name).get("_")
            final_state["process_output"] = process_output

        audit = getattr(self._ir.process, "audit", None)
        if audit:
            final_state["audit"] = audit.model_dump(exclude_none=True)

        return final_state

    def _schedule_if_ready(
        self,
        *,
        node_name: str,
        state: RunState,
        run_id: str,
    ) -> Optional[_InflightTask]:
        node = self._ir.resolved_nodes[node_name]
        incoming = self._incoming.get(node_name, [])

        if node_name == self._ir.trigger.name:
            resolved_input = dict(state["trigger_input"])
        else:
            if incoming:
                if any(
                    state["node_statuses"].get(edge.source.name) not in self._TERMINAL_STATUSES
                    for edge in incoming
                ):
                    return None

                firing_edges = []
                for edge in incoming:
                    if state["node_statuses"].get(edge.source.name) != "completed":
                        continue
                    if edge.edge.when and not eval_when(edge.edge.when, state, self._ir.trigger.name):
                        continue
                    firing_edges.append(edge)

                if not firing_edges:
                    state["node_statuses"][node_name] = "skipped"
                    state["execution_log"].append(
                        {
                            "event": "node_completed",
                            "node": node_name,
                            "status": "skipped",
                            "completed_at": _now_iso(),
                        }
                    )
                    return _InflightTask("", node_name, {}, "", _now_iso(), None)

                resolved_input = {}
                for edge in firing_edges:
                    part = resolve_mapping(edge.edge.mapping or {}, state, self._ir.trigger.name)
                    for key, value in part.items():
                        if key in resolved_input and resolved_input[key] != value:
                            state["node_statuses"][node_name] = "failed"
                            state["execution_log"].append(
                                {
                                    "event": "node_failed",
                                    "node": node_name,
                                    "status": "failed",
                                    "error": {
                                        "code": "input_conflict",
                                        "message": f"Conflicting mapped values for field {key!r}",
                                    },
                                    "completed_at": _now_iso(),
                                }
                            )
                            state["run_status"] = "failed"
                            return _InflightTask("", node_name, {}, "", _now_iso(), None)
                        resolved_input[key] = value
            else:
                resolved_input = {}

        try:
            _validate_payload(resolved_input, node.in_type, f"{node_name}.in")
        except _RuntimeValidationError as exc:
            state["node_statuses"][node_name] = "failed"
            state["execution_log"].append(
                {
                    "event": "node_failed",
                    "node": node_name,
                    "status": "failed",
                    "input": resolved_input,
                    "error": {"code": "input_validation_error", "message": str(exc)},
                    "completed_at": _now_iso(),
                }
            )
            state["run_status"] = "failed"
            return _InflightTask("", node_name, {}, "", _now_iso(), None)

        if not isinstance(node.node_type, NodeType):
            state["node_statuses"][node_name] = "failed"
            state["execution_log"].append(
                {
                    "event": "node_failed",
                    "node": node_name,
                    "status": "failed",
                    "error": {"code": "module_not_executable", "message": "Cannot execute unresolved module node"},
                    "completed_at": _now_iso(),
                }
            )
            state["run_status"] = "failed"
            return _InflightTask("", node_name, {}, "", _now_iso(), None)

        id_payload = self._idempotency_payload(node=node, payload=resolved_input)
        idempotency_key = compute_idempotency_key(run_id, node_name, id_payload)
        context = ExecutionContext(
            run_id=run_id,
            node_name=node_name,
            idempotency_key=idempotency_key,
            process_name=state["process_name"],
        )

        config = dict(node.instance.config or {})
        timeout_seconds = _parse_duration_seconds(config.get("timeout"))
        deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds
        started_at = _now_iso()

        task_id = self._node_adapter.start_node(
            node_name=node_name,
            node_type=node.node_type,
            input_payload=resolved_input,
            config=config,
            context=context,
        )

        state["node_statuses"][node_name] = "running"
        state["execution_log"].append(
            {
                "event": "node_scheduled",
                "node": node_name,
                "status": "running",
                "input": resolved_input,
                "idempotency_key": idempotency_key,
                "started_at": started_at,
            }
        )

        return _InflightTask(
            task_id=task_id,
            node_name=node_name,
            node_input=resolved_input,
            idempotency_key=idempotency_key,
            started_at=started_at,
            deadline_monotonic=deadline,
        )

    @staticmethod
    def _idempotency_payload(node: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
        stable = getattr(node.instance, "stable_input_fields", None) or []
        unstable = getattr(node.instance, "unstable_input_fields", None) or []
        if stable:
            return {key: payload[key] for key in stable if key in payload}
        if unstable:
            return {key: value for key, value in payload.items() if key not in set(unstable)}
        return payload
