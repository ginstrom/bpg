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
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from bpg.compiler.ir import ExecutionIR, ResolvedEdge
from bpg.models.schema import EdgeFailureAction, NodeStatus
from bpg.providers.base import (
    ExecutionContext,
    Provider,
    ProviderError,
    compute_idempotency_key,
)
from bpg.runtime.expr import eval_when, resolve_mapping
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
    ) -> None:
        self._ir = ir
        self._providers = providers
        self._checkpointer = checkpointer
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
        trigger_name: str = ir.process.trigger

        # Determine incoming edges for this node once at build time
        incoming: List[ResolvedEdge] = [
            re for re in ir.resolved_edges if re.edge.target == node_name
        ]
        is_trigger = len(incoming) == 0

        resolved_node = ir.resolved_nodes[node_name]

        def node_fn(state: RunState) -> dict:
            run_id: str = state["run_id"]

            # ----------------------------------------------------------
            # Trigger node: no incoming edges; pass-through trigger input
            # ----------------------------------------------------------
            if is_trigger:
                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.COMPLETED.value,
                    "timestamp": _now_iso(),
                    "output": state["trigger_input"],
                }
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
                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.SKIPPED.value,
                    "timestamp": _now_iso(),
                }
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
                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.FAILED.value,
                    "timestamp": _now_iso(),
                    "error": err_msg,
                }
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
                process_name=state["process_name"],
            )

            # ----------------------------------------------------------
            # Retry loop
            # ----------------------------------------------------------
            retry_policy = resolved_node.instance.retry
            max_attempts = retry_policy.max_attempts if retry_policy else 1
            retryable_codes = (
                set(retry_policy.retryable_errors) if retry_policy else set()
            )

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
                    # Otherwise continue to next attempt

            # ----------------------------------------------------------
            # Handle TimeoutError outcome
            # ----------------------------------------------------------
            if timed_out:
                on_timeout = resolved_node.instance.on_timeout
                timeout_output: Optional[Dict[str, Any]] = None
                if on_timeout and "out" in on_timeout:
                    timeout_output = on_timeout["out"]

                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.TIMED_OUT.value,
                    "timestamp": _now_iso(),
                    "input": input_payload,
                    "idempotency_key": idempotency_key,
                }
                state_update: dict = {
                    "node_statuses": {node_name: NodeStatus.TIMED_OUT.value},
                    "execution_log": [log_entry],
                    "failure_routes": {},
                }
                if timeout_output is not None:
                    state_update["node_outputs"] = {node_name: timeout_output}
                else:
                    state_update["node_outputs"] = {}
                return state_update

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

                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.FAILED.value,
                    "timestamp": _now_iso(),
                    "input": input_payload,
                    "error": str(last_exc),
                    "idempotency_key": idempotency_key,
                }
                return {
                    "node_outputs": {},
                    "node_statuses": {node_name: NodeStatus.FAILED.value},
                    "execution_log": [log_entry],
                    "failure_routes": failure_routes_update,
                }

            # ----------------------------------------------------------
            # Success
            # ----------------------------------------------------------
            log_entry = {
                "node": node_name,
                "status": NodeStatus.COMPLETED.value,
                "timestamp": _now_iso(),
                "input": input_payload,
                "output": output,
                "idempotency_key": idempotency_key,
            }
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
