"""LangGraph-backed runtime for BPG process execution.

Builds a LangGraph ``StateGraph`` from a compiled ``ExecutionIR``, where each
BPG node becomes a LangGraph node function.  Node functions evaluate incoming
edge conditions, resolve input mappings, invoke the appropriate provider, and
emit state updates.

The graph topology is a linear chain in topological order:

    START → topo[0] → topo[1] → ... → topo[-1] → END

Each node function is responsible for deciding whether to execute or skip
itself based on its incoming edges' ``when`` conditions.  This keeps the graph
structure simple while correctly implementing BPG's conditional branching.

Usage::

    runtime = LangGraphRuntime(ir=ir, providers={"agent.pipeline": my_provider})
    final_state = runtime.run(input_payload={"title": "Login broken", ...})
"""

from __future__ import annotations

import re as _re
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from bpg.compiler.ir import ExecutionIR, ResolvedEdge
from bpg.models.schema import BackoffStrategy, EdgeFailureAction, NodeStatus
from bpg.providers.base import (
    ExecutionContext,
    Provider,
    ProviderError,
    compute_idempotency_key,
)
from bpg.runtime.expr import eval_when, resolve_mapping
from bpg.runtime.observability import EventSink, NoopEventSink, RunEvent
from bpg.runtime.state import RunState


_DURATION_RE = _re.compile(r"^(\d+(?:\.\d+)?)\s*(ms|s|m|h|d)$")
_DURATION_UNITS = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}


def _parse_duration_seconds(s: str) -> Optional[float]:
    """Parse '5s', '10m', '2h' etc. into float seconds; returns None if unparseable."""
    if not s:
        return None
    m = _DURATION_RE.match(s.strip())
    if not m:
        return None
    return float(m.group(1)) * _DURATION_UNITS[m.group(2)]


def _now_iso() -> str:
    """Return current UTC time as an ISO 8601 string."""
    return datetime.now(tz=timezone.utc).isoformat()


_RETRY_INITIAL_DELAY_DEFAULT = 1.0   # seconds
_RETRY_MAX_DELAY_DEFAULT = 300.0     # seconds


class _RuntimeValidationError(Exception):
    """Raised when a runtime payload fails type validation."""


def _validate_payload(
    payload: Dict[str, Any],
    resolved_type: "ResolvedTypeDef",
    context: str,
) -> None:
    """Validate a payload dict against a ResolvedTypeDef.

    For primitive/opaque types (no fields), validation is a no-op.

    Raises:
        _RuntimeValidationError: On the first validation failure.
    """
    from bpg.compiler.ir import ResolvedTypeDef  # imported for type hint; already on path

    if not resolved_type.fields:
        return

    fields = resolved_type.fields

    # Required fields must be present and non-None
    missing = [
        f for f, ft in fields.items()
        if ft.is_required and (f not in payload or payload[f] is None)
    ]
    if missing:
        raise _RuntimeValidationError(
            f"{context}: missing required fields {sorted(missing)} "
            f"(type={resolved_type.name!r})"
        )

    # No unknown fields
    extra = sorted(set(payload.keys()) - set(fields.keys()))
    if extra:
        raise _RuntimeValidationError(
            f"{context}: unexpected fields {extra} not in type {resolved_type.name!r}"
        )

    # Type-check each present value
    for fname, val in payload.items():
        if fname not in fields or val is None:
            continue
        ft = fields[fname]
        if ft.base == "bool":
            if not isinstance(val, bool):
                raise _RuntimeValidationError(
                    f"{context}.{fname}: expected bool, got {type(val).__name__}"
                )
        elif ft.base == "number":
            if isinstance(val, bool) or not isinstance(val, (int, float)):
                raise _RuntimeValidationError(
                    f"{context}.{fname}: expected number, got {type(val).__name__}"
                )
        elif ft.base == "string":
            if not isinstance(val, str):
                raise _RuntimeValidationError(
                    f"{context}.{fname}: expected string, got {type(val).__name__}"
                )
        elif ft.base == "enum":
            if ft.enum_values and val not in ft.enum_values:
                raise _RuntimeValidationError(
                    f"{context}.{fname}: {val!r} not in enum {list(ft.enum_values)}"
                )
        elif ft.base == "list":
            if not isinstance(val, list):
                raise _RuntimeValidationError(
                    f"{context}.{fname}: expected list, got {type(val).__name__}"
                )


def _compute_retry_delay(
    attempt: int,  # 0-based index of the *retry* (0 = first retry, after attempt 0)
    backoff: BackoffStrategy,
    initial_delay: float,
    max_delay: float,
) -> float:
    """Return the sleep duration (seconds) before the next retry attempt.

    Args:
        attempt: 0-based retry counter (0 = first retry).
        backoff: Backoff strategy from the node's :class:`RetryPolicy`.
        initial_delay: Base delay in seconds.
        max_delay: Upper bound on the computed delay.

    Returns:
        Seconds to sleep before the next attempt, capped at ``max_delay``.
    """
    if backoff == BackoffStrategy.CONSTANT:
        delay = initial_delay
    elif backoff == BackoffStrategy.LINEAR:
        delay = initial_delay * (attempt + 1)
    else:  # EXPONENTIAL (default)
        delay = initial_delay * (2 ** attempt)
    return min(delay, max_delay)


class LangGraphRuntime:
    """Execute a BPG process using LangGraph as the orchestration engine.

    Args:
        ir: Compiled and validated :class:`ExecutionIR` for the process.
        providers: Dict mapping provider identifier strings to
            :class:`Provider` instances (e.g. ``{"agent.pipeline": my_agent}``).
        checkpointer: Optional LangGraph checkpointer (e.g. ``MemorySaver``
            or ``SqliteSaver``) for state persistence and resumability.
    """

    def __init__(
        self,
        ir: ExecutionIR,
        providers: Dict[str, Provider],
        checkpointer=None,
        event_sink: Optional[EventSink] = None,
    ) -> None:
        self._ir = ir
        self._providers = providers
        self._checkpointer = checkpointer
        self._sink: EventSink = event_sink if event_sink is not None else NoopEventSink()
        self._graph = self._build_graph()

    # ------------------------------------------------------------------
    # Graph construction
    # ------------------------------------------------------------------

    def _build_graph(self):
        """Build and compile a LangGraph StateGraph from the ExecutionIR."""
        builder = StateGraph(RunState)
        topo: List[str] = self._ir.topological_order

        # Add one LangGraph node per BPG node
        for node_name in topo:
            fn = self._make_node_fn(node_name)
            builder.add_node(node_name, fn)

        # Wire: START → first → ... → last → END (linear chain)
        builder.add_edge(START, topo[0])
        for i in range(len(topo) - 1):
            builder.add_edge(topo[i], topo[i + 1])
        builder.add_edge(topo[-1], END)

        return builder.compile(checkpointer=self._checkpointer)

    # ------------------------------------------------------------------
    # Node function factory
    # ------------------------------------------------------------------

    def _make_node_fn(self, node_name: str) -> Callable[[RunState], dict]:
        """Return a LangGraph node function for the given BPG node.

        The returned function captures ``node_name`` and the runtime's ``ir``
        and ``providers`` via closure.  It is called by LangGraph with the
        current :class:`RunState` and must return a partial-state dict.
        """
        ir = self._ir
        providers = self._providers
        sink = self._sink
        trigger_name: str = ir.process.trigger

        # Determine incoming edges for this node once at build time
        incoming: List[ResolvedEdge] = [
            re for re in ir.resolved_edges if re.edge.target == node_name
        ]
        is_trigger = len(incoming) == 0

        resolved_node = ir.resolved_nodes[node_name]

        def node_fn(state: RunState) -> dict:
            run_id: str = state["run_id"]
            process_name: str = state["process_name"]

            def _base_event(**extra) -> RunEvent:
                """Build a RunEvent with the fields common to every transition."""
                ev: RunEvent = {
                    "run_id": run_id,
                    "process_name": process_name,
                    "node": node_name,
                    "timestamp": _now_iso(),
                }
                ev.update(extra)  # type: ignore[typeddict-item]
                return ev

            # ----------------------------------------------------------
            # Trigger node: no incoming edges; pass-through trigger input
            # ----------------------------------------------------------
            if is_trigger:
                ts = _now_iso()
                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.COMPLETED.value,
                    "timestamp": ts,
                    "output": state["trigger_input"],
                }
                sink.emit(_base_event(
                    event_type="node_completed",
                    status=NodeStatus.COMPLETED.value,
                    output=state["trigger_input"],
                    timestamp=ts,
                ))
                return {
                    "node_outputs": {node_name: state["trigger_input"]},
                    "node_statuses": {node_name: NodeStatus.COMPLETED.value},
                    "execution_log": [log_entry],
                    "failure_routes": {},
                }

            # ----------------------------------------------------------
            # Check failure routes before evaluating normal edges
            # ----------------------------------------------------------
            failure_input = state.get("failure_routes", {}).get(node_name)

            # ----------------------------------------------------------
            # Check whether any incoming edge fires (skipped if failure route)
            # ----------------------------------------------------------
            firing_edge: Optional[ResolvedEdge] = None
            if failure_input is None:
                for resolved_edge in incoming:
                    src_name = resolved_edge.edge.source
                    src_status = state["node_statuses"].get(src_name)

                    # Source must have completed
                    if src_status != NodeStatus.COMPLETED.value:
                        continue

                    # Evaluate when condition (if present)
                    if resolved_edge.edge.when is not None:
                        try:
                            condition_met = eval_when(
                                resolved_edge.edge.when, state, trigger_name
                            )
                        except Exception:
                            condition_met = False
                        if not condition_met:
                            continue

                    firing_edge = resolved_edge
                    break

            # Skip if no edge fires AND no failure route
            if firing_edge is None and failure_input is None:
                ts = _now_iso()
                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.SKIPPED.value,
                    "timestamp": ts,
                }
                sink.emit(_base_event(
                    event_type="node_skipped",
                    status=NodeStatus.SKIPPED.value,
                    timestamp=ts,
                ))
                return {
                    "node_outputs": {},
                    "node_statuses": {node_name: NodeStatus.SKIPPED.value},
                    "execution_log": [log_entry],
                    "failure_routes": {},
                }

            # ----------------------------------------------------------
            # Resolve input payload
            # ----------------------------------------------------------
            if failure_input is not None:
                input_payload = failure_input
            elif firing_edge is not None and firing_edge.edge.mapping:
                input_payload = resolve_mapping(
                    firing_edge.edge.mapping, state, trigger_name
                )
            else:
                input_payload = {}

            # ----------------------------------------------------------
            # Validate input payload against node's in type (§7 step 4)
            # ----------------------------------------------------------
            try:
                _validate_payload(
                    input_payload,
                    resolved_node.in_type,
                    f"node '{node_name}' input",
                )
            except _RuntimeValidationError as exc:
                err_msg = str(exc)
                ts = _now_iso()
                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.FAILED.value,
                    "timestamp": ts,
                    "error": err_msg,
                }
                sink.emit(_base_event(
                    event_type="node_failed",
                    status=NodeStatus.FAILED.value,
                    error=err_msg,
                    timestamp=ts,
                ))
                return {
                    "node_outputs": {},
                    "node_statuses": {node_name: NodeStatus.FAILED.value},
                    "execution_log": [log_entry],
                    "failure_routes": {},
                }

            # ----------------------------------------------------------
            # Determine effective timeout
            # ----------------------------------------------------------
            edge_timeout_str = firing_edge.edge.timeout if firing_edge else None
            node_timeout_str = resolved_node.node_type.timeout_default
            effective_timeout = _parse_duration_seconds(
                edge_timeout_str or node_timeout_str or ""
            )

            # ----------------------------------------------------------
            # Invoke the provider
            # ----------------------------------------------------------
            provider_id = resolved_node.node_type.provider
            provider = providers.get(provider_id)
            if provider is None:
                err_msg = f"No provider registered for '{provider_id}'"
                ts = _now_iso()
                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.FAILED.value,
                    "timestamp": ts,
                    "error": err_msg,
                }
                sink.emit(_base_event(
                    event_type="node_failed",
                    status=NodeStatus.FAILED.value,
                    error=err_msg,
                    timestamp=ts,
                ))
                return {
                    "node_outputs": {},
                    "node_statuses": {node_name: NodeStatus.FAILED.value},
                    "execution_log": [log_entry],
                    "failure_routes": {},
                }

            idempotency_key = compute_idempotency_key(run_id, node_name, input_payload)
            context = ExecutionContext(
                run_id=run_id,
                node_name=node_name,
                idempotency_key=idempotency_key,
                process_name=process_name,
            )

            # ----------------------------------------------------------
            # Retry loop setup
            # ----------------------------------------------------------
            retry_policy = resolved_node.instance.retry
            max_attempts = retry_policy.max_attempts if retry_policy else 1
            retryable_codes = (
                set(retry_policy.retryable_errors) if retry_policy else set()
            )
            backoff_strategy = (
                retry_policy.backoff if retry_policy else BackoffStrategy.EXPONENTIAL
            )
            initial_delay_s = _parse_duration_seconds(
                retry_policy.initial_delay or ""
            ) if retry_policy else None
            max_delay_s = _parse_duration_seconds(
                retry_policy.max_delay or ""
            ) if retry_policy else None
            initial_delay_s = initial_delay_s if initial_delay_s is not None else _RETRY_INITIAL_DELAY_DEFAULT
            max_delay_s = max_delay_s if max_delay_s is not None else _RETRY_MAX_DELAY_DEFAULT

            # node_started — emitted once before the first attempt
            sink.emit(_base_event(
                event_type="node_started",
                status=NodeStatus.RUNNING.value,
                input=input_payload,
                idempotency_key=idempotency_key,
            ))

            last_exc: Optional[ProviderError] = None
            output: Optional[Dict[str, Any]] = None
            timed_out = False

            for _attempt in range(max_attempts):
                try:
                    handle = provider.invoke(
                        input_payload, dict(resolved_node.instance.config), context
                    )
                    output = provider.await_result(handle, timeout=effective_timeout)
                    last_exc = None
                    break
                except TimeoutError:
                    timed_out = True
                    break
                except ProviderError as exc:
                    last_exc = exc
                    # Non-retryable error — stop immediately
                    if not exc.retryable:
                        break
                    # Retryable codes filter — stop if code not in allowed set
                    if retryable_codes and exc.code not in retryable_codes:
                        break
                    # More attempts remain — compute backoff and sleep
                    if _attempt < max_attempts - 1:
                        delay = _compute_retry_delay(
                            _attempt, backoff_strategy, initial_delay_s, max_delay_s
                        )
                        sink.emit(_base_event(
                            event_type="node_retrying",
                            status=NodeStatus.RUNNING.value,
                            attempt=_attempt + 1,
                            delay_seconds=delay,
                            error=str(exc),
                            error_code=exc.code,
                            idempotency_key=idempotency_key,
                        ))
                        time.sleep(delay)

            # ----------------------------------------------------------
            # Handle TimeoutError outcome
            # ----------------------------------------------------------
            if timed_out:
                on_timeout = resolved_node.instance.on_timeout
                timeout_output: Optional[Dict[str, Any]] = None
                if on_timeout and "out" in on_timeout:
                    timeout_output = on_timeout["out"]

                ts = _now_iso()
                if timeout_output is not None:
                    # Spec §9: on_timeout.out continues the run; treat as completed
                    # for routing, but mark synthetic=True in the log for audit.
                    log_entry = {
                        "node": node_name,
                        "status": NodeStatus.TIMED_OUT.value,
                        "effective_status": NodeStatus.COMPLETED.value,
                        "synthetic": True,
                        "timestamp": ts,
                        "input": input_payload,
                        "output": timeout_output,
                        "idempotency_key": idempotency_key,
                    }
                    sink.emit(_base_event(
                        event_type="node_timed_out",
                        status=NodeStatus.TIMED_OUT.value,
                        effective_status=NodeStatus.COMPLETED.value,
                        synthetic=True,
                        input=input_payload,
                        output=timeout_output,
                        idempotency_key=idempotency_key,
                        timestamp=ts,
                    ))
                    return {
                        "node_outputs": {node_name: timeout_output},
                        "node_statuses": {node_name: NodeStatus.COMPLETED.value},
                        "execution_log": [log_entry],
                        "failure_routes": {},
                    }
                else:
                    # No fallback output — stop routing for this branch.
                    log_entry = {
                        "node": node_name,
                        "status": NodeStatus.TIMED_OUT.value,
                        "timestamp": ts,
                        "input": input_payload,
                        "idempotency_key": idempotency_key,
                    }
                    sink.emit(_base_event(
                        event_type="node_timed_out",
                        status=NodeStatus.TIMED_OUT.value,
                        input=input_payload,
                        idempotency_key=idempotency_key,
                        timestamp=ts,
                    ))
                    return {
                        "node_outputs": {},
                        "node_statuses": {node_name: NodeStatus.TIMED_OUT.value},
                        "execution_log": [log_entry],
                        "failure_routes": {},
                    }

            # ----------------------------------------------------------
            # Handle exhausted retries (ProviderError)
            # ----------------------------------------------------------
            if last_exc is not None:
                failure_routes_update: Dict[str, Dict[str, Any]] = {}
                if firing_edge is not None:
                    on_failure = firing_edge.edge.on_failure
                    if (
                        on_failure is not None
                        and on_failure.action == EdgeFailureAction.ROUTE.value
                        and on_failure.to is not None
                    ):
                        failure_routes_update[on_failure.to] = input_payload

                ts = _now_iso()
                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.FAILED.value,
                    "timestamp": ts,
                    "input": input_payload,
                    "error": str(last_exc),
                    "idempotency_key": idempotency_key,
                }
                sink.emit(_base_event(
                    event_type="node_failed",
                    status=NodeStatus.FAILED.value,
                    input=input_payload,
                    error=str(last_exc),
                    error_code=last_exc.code,
                    idempotency_key=idempotency_key,
                    timestamp=ts,
                ))
                return {
                    "node_outputs": {},
                    "node_statuses": {node_name: NodeStatus.FAILED.value},
                    "execution_log": [log_entry],
                    "failure_routes": failure_routes_update,
                }

            # ----------------------------------------------------------
            # Validate provider output against node's out type (§7 step 7)
            # ----------------------------------------------------------
            if output is not None:
                try:
                    _validate_payload(
                        output,
                        resolved_node.out_type,
                        f"node '{node_name}' output",
                    )
                except _RuntimeValidationError as exc:
                    err_msg = str(exc)
                    ts = _now_iso()
                    log_entry = {
                        "node": node_name,
                        "status": NodeStatus.FAILED.value,
                        "timestamp": ts,
                        "error": err_msg,
                    }
                    sink.emit(_base_event(
                        event_type="node_failed",
                        status=NodeStatus.FAILED.value,
                        error=err_msg,
                        timestamp=ts,
                    ))
                    return {
                        "node_outputs": {},
                        "node_statuses": {node_name: NodeStatus.FAILED.value},
                        "execution_log": [log_entry],
                        "failure_routes": {},
                    }

            # ----------------------------------------------------------
            # Success
            # ----------------------------------------------------------
            ts = _now_iso()
            log_entry = {
                "node": node_name,
                "status": NodeStatus.COMPLETED.value,
                "timestamp": ts,
                "input": input_payload,
                "output": output,
                "idempotency_key": idempotency_key,
            }
            sink.emit(_base_event(
                event_type="node_completed",
                status=NodeStatus.COMPLETED.value,
                input=input_payload,
                output=output,
                idempotency_key=idempotency_key,
                timestamp=ts,
            ))
            return {
                "node_outputs": {node_name: output},
                "node_statuses": {node_name: NodeStatus.COMPLETED.value},
                "execution_log": [log_entry],
                "failure_routes": {},
            }

        return node_fn

    # ------------------------------------------------------------------
    # Public run method
    # ------------------------------------------------------------------

    def run(
        self,
        input_payload: Dict[str, Any],
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute the process end-to-end and return the final RunState.

        Args:
            input_payload: The trigger input conforming to the trigger node's
                ``in`` type.
            run_id: Optional run identifier; a UUID4 is generated when omitted.

        Returns:
            The final :class:`RunState` dict after all nodes have executed.
        """
        if run_id is None:
            run_id = str(uuid.uuid4())

        process_name: str = (
            self._ir.process.metadata.name
            if self._ir.process.metadata
            else self._ir.process.trigger
        )

        # Validate trigger input against the effective input type.
        # When the trigger node's in_type has no fields (e.g. opaque ``object``),
        # fall back to the first downstream node's in_type so that the process's
        # external API contract is still enforced at the boundary.
        trigger_resolved = self._ir.trigger
        effective_in_type = trigger_resolved.in_type
        if not effective_in_type.fields:
            # Look for the first outgoing edge target that has a structured type
            for re in self._ir.resolved_edges:
                if re.edge.source == trigger_resolved.name and re.target.in_type.fields:
                    effective_in_type = re.target.in_type
                    break
        try:
            _validate_payload(
                input_payload,
                effective_in_type,
                "trigger input",
            )
        except _RuntimeValidationError as exc:
            raise ValueError(f"Trigger input validation failed: {exc}") from exc

        initial_state: RunState = {
            "run_id": run_id,
            "process_name": process_name,
            "trigger_input": input_payload,
            "node_outputs": {},
            "node_statuses": {},
            "execution_log": [],
            "failure_routes": {},
        }

        config = {"configurable": {"thread_id": run_id}}
        final_state = self._graph.invoke(initial_state, config=config)
        return final_state

    def resume(
        self,
        run_id: str,
        response: Any,
    ) -> Dict[str, Any]:
        """Resume a graph suspended by a human-in-the-loop ``interrupt()``.

        Args:
            run_id: The run identifier (must match the original ``run()`` call).
            response: The value to inject as the ``interrupt()`` return — typically
                the human's response payload (e.g. ``{"approved": True}``).

        Returns:
            The final :class:`RunState` dict after all nodes have executed.

        Raises:
            ValueError: If the runtime was not built with a checkpointer.
        """
        from langgraph.types import Command

        if self._checkpointer is None:
            raise ValueError(
                "LangGraphRuntime.resume() requires a checkpointer.  "
                "Pass a MemorySaver or SqliteSaver to the constructor."
            )
        config = {"configurable": {"thread_id": run_id}}
        return self._graph.invoke(Command(resume=response), config=config)
