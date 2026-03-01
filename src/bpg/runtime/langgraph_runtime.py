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
import copy
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from langgraph.graph import END, START, StateGraph

from bpg.compiler.ir import ExecutionIR, ResolvedEdge
from bpg.models.schema import BackoffStrategy, EdgeFailureAction, NodeStatus
from bpg.providers.base import (
    ExecutionContext,
    ExecutionStatus,
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
_HUMAN_PROVIDER_IDS = frozenset({"slack.interactive", "dashboard.form"})


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
        initial_result_cache: Optional[Dict[str, Dict[str, Any]]] = None,
    ) -> None:
        self._ir = ir
        self._providers = providers
        self._checkpointer = checkpointer
        self._sink: EventSink = event_sink if event_sink is not None else NoopEventSink()
        self._result_cache: Dict[str, Dict[str, Any]] = dict(initial_result_cache or {})
        self._cancel_events: Dict[str, threading.Event] = {}
        self._inflight_handles: Dict[str, tuple[Provider, Any]] = {}
        self._runtime_lock = threading.Lock()
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

    @staticmethod
    def _idempotency_payload(node: Any, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Return payload subset used for idempotency key computation."""
        stable = getattr(node.instance, "stable_input_fields", None) or []
        unstable = getattr(node.instance, "unstable_input_fields", None) or []
        if stable:
            return {k: payload[k] for k in stable if k in payload}
        if unstable:
            return {k: v for k, v in payload.items() if k not in set(unstable)}
        return payload

    @staticmethod
    def _principal_value(
        *,
        field_name: str,
        trigger_input: Dict[str, Any],
        actor: Dict[str, Any],
        actor_id: Any,
        actor_roles: List[str],
    ) -> Any:
        if field_name == "__actor_id__":
            return actor_id
        if field_name == "__actor_roles__":
            return actor_roles
        if field_name.startswith("actor."):
            return actor.get(field_name.split(".", 1)[1])
        return trigger_input.get(field_name)

    @staticmethod
    def _principal_overlap(left: Any, right: Any) -> bool:
        if left is None or right is None:
            return False
        if isinstance(left, list) and isinstance(right, list):
            return bool(set(map(str, left)) & set(map(str, right)))
        if isinstance(left, list):
            return str(right) in {str(v) for v in left}
        if isinstance(right, list):
            return str(left) in {str(v) for v in right}
        return str(left) == str(right)

    @staticmethod
    def _escalation_routes(
        policy: Any,
        node_name: str,
        event_name: str,
        attempts: int,
        payload: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        routes: Dict[str, Dict[str, Any]] = {}
        if not policy or not policy.escalation:
            return routes
        for rule in policy.escalation:
            if rule.get("node") != node_name:
                continue
            rule_event = rule.get("on", rule.get(True))
            if rule_event != event_name:
                continue
            if attempts < int(rule.get("after_attempts", 1)):
                continue
            target = rule.get("route_to")
            if isinstance(target, str) and target:
                routes[target] = payload
        return routes

    def _invoke_provider_with_timeout(
        self,
        *,
        provider: Provider,
        input_payload: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
        timeout: Optional[float],
        cancel_event: threading.Event,
    ) -> tuple[Optional[Any], Optional[ProviderError], bool]:
        """Invoke provider in isolation to enforce timeout even if invoke blocks."""
        holder: Dict[str, Any] = {"handle": None, "error": None}
        done = threading.Event()

        def _worker() -> None:
            try:
                holder["handle"] = provider.invoke(input_payload, config, context)
            except TimeoutError as exc:
                holder["error"] = exc
            except ProviderError as exc:
                holder["error"] = exc
            except Exception as exc:
                holder["error"] = ProviderError(
                    code="provider_unavailable",
                        message=str(exc),
                        retryable=False,
                    )
            finally:
                done.set()

        threading.Thread(target=_worker, daemon=True).start()

        deadline = None if timeout is None else (time.monotonic() + timeout)
        while not done.wait(timeout=0.05):
            if cancel_event.is_set():
                return None, ProviderError("cancelled", "Run cancelled", False), False
            if deadline is not None and time.monotonic() >= deadline:
                return None, None, True

        err = holder.get("error")
        if isinstance(err, TimeoutError):
            return None, None, True
        if isinstance(err, ProviderError):
            return None, err, False
        return holder.get("handle"), None, False

    @staticmethod
    def _poll_interval_seconds(handle: Any) -> float:
        provider_data = getattr(handle, "provider_data", {}) or {}
        value = provider_data.get("poll_interval", 0.05)
        try:
            interval = float(value)
        except (TypeError, ValueError):
            return 0.05
        return interval if interval > 0 else 0.05

    def _await_provider_with_polling(
        self,
        *,
        provider: Provider,
        handle: Any,
        timeout: Optional[float],
        cancel_event: threading.Event,
    ) -> tuple[Optional[Dict[str, Any]], Optional[ProviderError], bool]:
        """Drive provider completion with poll() and runtime-managed timeout/cancel."""
        deadline = None if timeout is None else (time.monotonic() + timeout)
        poll_interval = self._poll_interval_seconds(handle)

        while True:
            if cancel_event.is_set():
                try:
                    provider.cancel(handle)
                except Exception:
                    pass
                return None, ProviderError("cancelled", "Run cancelled", False), False

            if deadline is not None and time.monotonic() >= deadline:
                try:
                    provider.cancel(handle)
                except Exception:
                    pass
                return None, None, True

            try:
                status = provider.poll(handle)
            except ProviderError as exc:
                return None, exc, False
            except Exception as exc:
                return None, ProviderError("provider_unavailable", str(exc), False), False

            if status == ExecutionStatus.RUNNING:
                if timeout is None:
                    try:
                        output = provider.await_(handle, timeout=None)
                        return output, None, False
                    except TimeoutError:
                        return None, None, True
                    except ProviderError as exc:
                        return None, exc, False
                    except Exception as exc:
                        return None, ProviderError("provider_unavailable", str(exc), False), False
                time.sleep(poll_interval)
                continue

            try:
                output = provider.await_(handle, timeout=0.0)
                return output, None, False
            except TimeoutError:
                if deadline is not None and time.monotonic() >= deadline:
                    return None, None, True
                return None, ProviderError("provider_unavailable", "provider await timed out", False), False
            except ProviderError as exc:
                return None, exc, False
            except Exception as exc:
                return None, ProviderError("provider_unavailable", str(exc), False), False

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
        is_trigger = node_name == ir.trigger.name

        resolved_node = ir.resolved_nodes[node_name]
        policy = ir.process.policy

        # Check for PII redaction policy
        redact_fields = set()
        if ir.process.policy and ir.process.policy.pii_redaction:
            for pr in ir.process.policy.pii_redaction:
                if pr.node == node_name:
                    redact_fields.update(pr.redact_fields)

        def _redact(data: Any) -> Any:
            if not redact_fields or not isinstance(data, (dict, list)):
                return data
            redacted = copy.deepcopy(data)

            def _parts(path: str) -> List[str]:
                return [p for p in path.replace("[]", ".[]").split(".") if p]

            def _mask(value: Any, parts: List[str]) -> Any:
                if not parts:
                    return "[REDACTED]"
                head = parts[0]
                tail = parts[1:]
                if isinstance(value, dict):
                    if head == "*":
                        for k in list(value.keys()):
                            value[k] = _mask(value[k], tail)
                    elif head in value:
                        value[head] = _mask(value[head], tail)
                    return value
                if isinstance(value, list):
                    if head in {"[]", "*"}:
                        for i, item in enumerate(value):
                            value[i] = _mask(item, tail)
                    elif head.isdigit():
                        idx = int(head)
                        if 0 <= idx < len(value):
                            value[idx] = _mask(value[idx], tail)
                    return value
                return value

            for field in redact_fields:
                redacted = _mask(redacted, _parts(field))
            return redacted

        def node_fn(state: RunState) -> dict:
            run_id: str = state["run_id"]
            process_name: str = state["process_name"]
            with self._runtime_lock:
                cancel_event = self._cancel_events.setdefault(run_id, threading.Event())

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

            if state.get("run_status") == NodeStatus.FAILED.value:
                return {
                    "node_outputs": {},
                    "node_statuses": {node_name: NodeStatus.SKIPPED.value},
                    "execution_log": [{
                        "node": node_name,
                        "status": NodeStatus.SKIPPED.value,
                        "timestamp": _now_iso(),
                    }],
                    "failure_routes": {},
                }
            if state.get("run_status") == NodeStatus.CANCELLED.value or cancel_event.is_set():
                ts = _now_iso()
                sink.emit(_base_event(
                    event_type="node_failed",
                    status=NodeStatus.CANCELLED.value,
                    error="Run cancelled",
                    error_code="cancelled",
                    timestamp=ts,
                ))
                return {
                    "node_outputs": {},
                    "node_statuses": {node_name: NodeStatus.CANCELLED.value},
                    "execution_log": [{
                        "node": node_name,
                        "status": NodeStatus.CANCELLED.value,
                        "timestamp": ts,
                        "error": "Run cancelled",
                    }],
                    "failure_routes": {},
                    "run_status": NodeStatus.CANCELLED.value,
                }

            # ----------------------------------------------------------
            # Declared trigger node: pass-through trigger input
            # ----------------------------------------------------------
            if is_trigger:
                ts = _now_iso()
                redacted_output = _redact(state["trigger_input"])
                log_entry = {
                    "node": node_name,
                    "status": NodeStatus.COMPLETED.value,
                    "timestamp": ts,
                    "output": redacted_output,
                }
                sink.emit(_base_event(
                    event_type="node_completed",
                    status=NodeStatus.COMPLETED.value,
                    output=redacted_output,
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
            firing_edges: List[ResolvedEdge] = []
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

                    firing_edges.append(resolved_edge)

            # Skip if no edge fires AND no failure route
            if not firing_edges and failure_input is None:
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
            else:
                merged_mapping: Dict[str, Any] = {}
                for edge_ref in firing_edges:
                    edge_mapping = edge_ref.edge.mapping or {}
                    if not edge_mapping:
                        continue
                    resolved = resolve_mapping(edge_mapping, state, trigger_name)
                    for k, v in resolved.items():
                        if k in merged_mapping and merged_mapping[k] != v:
                            err_msg = (
                                f"Conflicting mapping for field {k!r} from multiple incoming edges"
                            )
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
                                "run_status": NodeStatus.FAILED.value,
                            }
                        merged_mapping[k] = v
                input_payload = merged_mapping

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
            edge_timeouts = [
                _parse_duration_seconds(re.edge.timeout or "")
                for re in firing_edges
                if re.edge.timeout
            ]
            edge_timeouts = [t for t in edge_timeouts if t is not None]
            node_timeout_str = resolved_node.node_type.timeout_default
            if edge_timeouts:
                effective_timeout = min(edge_timeouts)
            else:
                effective_timeout = _parse_duration_seconds(node_timeout_str or "")

            # ----------------------------------------------------------
            # Policy checks (access_control + separation_of_duties)
            # ----------------------------------------------------------
            provider_id = resolved_node.node_type.provider
            actor = state["trigger_input"].get("__actor__", {})
            actor_id = None
            actor_roles: List[str] = []
            if isinstance(actor, dict):
                actor_id = actor.get("id")
                raw_roles = actor.get("roles", [])
                if isinstance(raw_roles, str):
                    actor_roles = [raw_roles]
                elif isinstance(raw_roles, list):
                    actor_roles = [str(r) for r in raw_roles]
            if not actor_id:
                actor_id = state["trigger_input"].get("__actor_id__")
            if not actor_roles:
                raw_roles = state["trigger_input"].get("__actor_roles__", [])
                if isinstance(raw_roles, str):
                    actor_roles = [raw_roles]
                elif isinstance(raw_roles, list):
                    actor_roles = [str(r) for r in raw_roles]

            if policy and provider_id in _HUMAN_PROVIDER_IDS:
                if policy.access_control:
                    allowed_roles = None
                    for ac in policy.access_control:
                        if ac.node == node_name:
                            allowed_roles = set(ac.allowed_roles)
                            break
                    if allowed_roles is not None and not (set(actor_roles) & allowed_roles):
                        ts = _now_iso()
                        err_msg = (
                            f"Access denied for node '{node_name}': "
                            f"required one of roles {sorted(allowed_roles)}, got {actor_roles}"
                        )
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
                            error_code="policy_access_denied",
                            timestamp=ts,
                        ))
                        return {
                            "node_outputs": {},
                            "node_statuses": {node_name: NodeStatus.FAILED.value},
                            "execution_log": [log_entry],
                            "failure_routes": {},
                            "run_status": NodeStatus.FAILED.value,
                        }

                if policy.separation_of_duties and policy.separation_of_duties.get("reporter_cannot_approve"):
                    reporter_id = (
                        state["trigger_input"].get("reporter_id")
                        or state["trigger_input"].get("reporter_email")
                    )
                    if actor_id and reporter_id and str(actor_id) == str(reporter_id):
                        ts = _now_iso()
                        err_msg = (
                            "Separation-of-duties violation: reporter and approver are the same principal"
                        )
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
                            error_code="policy_separation_of_duties",
                            timestamp=ts,
                        ))
                        return {
                            "node_outputs": {},
                            "node_statuses": {node_name: NodeStatus.FAILED.value},
                            "execution_log": [log_entry],
                            "failure_routes": {},
                            "run_status": NodeStatus.FAILED.value,
                        }

                if policy.separation_of_duties:
                    for rule in policy.separation_of_duties.get("rules", []) or []:
                        rule_nodes = rule.get("nodes", [])
                        if rule_nodes and node_name not in rule_nodes:
                            continue
                        left = self._principal_value(
                            field_name=rule["left_principal_field"],
                            trigger_input=state["trigger_input"],
                            actor=actor if isinstance(actor, dict) else {},
                            actor_id=actor_id,
                            actor_roles=actor_roles,
                        )
                        right = self._principal_value(
                            field_name=rule["right_principal_field"],
                            trigger_input=state["trigger_input"],
                            actor=actor if isinstance(actor, dict) else {},
                            actor_id=actor_id,
                            actor_roles=actor_roles,
                        )
                        if not self._principal_overlap(left, right):
                            continue
                        ts = _now_iso()
                        err_msg = rule.get(
                            "message",
                            (
                                "Separation-of-duties violation: "
                                f"{rule['left_principal_field']} overlaps "
                                f"{rule['right_principal_field']}"
                            ),
                        )
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
                            error_code="policy_separation_of_duties",
                            timestamp=ts,
                        ))
                        return {
                            "node_outputs": {},
                            "node_statuses": {node_name: NodeStatus.FAILED.value},
                            "execution_log": [log_entry],
                            "failure_routes": {},
                            "run_status": NodeStatus.FAILED.value,
                        }

            # ----------------------------------------------------------
            # Invoke the provider
            # ----------------------------------------------------------
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
                    "run_status": NodeStatus.FAILED.value,
                }

            idempotency_payload = self._idempotency_payload(resolved_node, input_payload)
            idempotency_key = compute_idempotency_key(run_id, node_name, idempotency_payload)
            context = ExecutionContext(
                run_id=run_id,
                node_name=node_name,
                idempotency_key=idempotency_key,
                process_name=process_name,
            )

            cached_output = self._result_cache.get(idempotency_key)
            if cached_output is not None:
                ts = _now_iso()
                redacted_input = _redact(input_payload)
                redacted_output = _redact(cached_output)
                sink.emit(_base_event(
                    event_type="node_completed",
                    status=NodeStatus.COMPLETED.value,
                    input=redacted_input,
                    output=redacted_output,
                    idempotency_key=idempotency_key,
                    cache_hit=True,
                    timestamp=ts,
                ))
                return {
                    "node_outputs": {node_name: cached_output},
                    "node_statuses": {node_name: NodeStatus.COMPLETED.value},
                    "execution_log": [{
                        "node": node_name,
                        "status": NodeStatus.COMPLETED.value,
                        "timestamp": ts,
                        "input": redacted_input,
                        "output": redacted_output,
                        "idempotency_key": idempotency_key,
                        "cache_hit": True,
                    }],
                    "failure_routes": {},
                    "run_status": state.get("run_status", "running"),
                }

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
                input=_redact(input_payload),
                idempotency_key=idempotency_key,
            ))

            last_exc: Optional[ProviderError] = None
            output: Optional[Dict[str, Any]] = None
            timed_out = False
            attempts_used = 0

            for _attempt in range(max_attempts):
                attempts_used = _attempt + 1
                if provider_id in _HUMAN_PROVIDER_IDS:
                    try:
                        handle = provider.invoke(
                            input_payload, dict(resolved_node.instance.config), context
                        )
                        with self._runtime_lock:
                            self._inflight_handles[run_id] = (provider, handle)
                        if cancel_event.is_set():
                            provider.cancel(handle)
                            raise ProviderError(
                                code="cancelled",
                                message="Run cancelled",
                                retryable=False,
                            )
                        output = provider.await_(handle, timeout=effective_timeout)
                        with self._runtime_lock:
                            self._inflight_handles.pop(run_id, None)
                        attempt_exc = None
                    except TimeoutError:
                        with self._runtime_lock:
                            self._inflight_handles.pop(run_id, None)
                        timed_out = True
                        attempt_exc = None
                    except ProviderError as exc:
                        with self._runtime_lock:
                            self._inflight_handles.pop(run_id, None)
                        attempt_exc = exc
                else:
                    attempt_started = time.monotonic()
                    handle, attempt_exc, timed_out = self._invoke_provider_with_timeout(
                        provider=provider,
                        input_payload=input_payload,
                        config=dict(resolved_node.instance.config),
                        context=context,
                        timeout=effective_timeout,
                        cancel_event=cancel_event,
                    )
                    output = None
                    if handle is not None and attempt_exc is None and not timed_out:
                        remaining_timeout = None
                        if effective_timeout is not None:
                            remaining_timeout = effective_timeout - (time.monotonic() - attempt_started)
                            if remaining_timeout <= 0:
                                timed_out = True
                        if not timed_out:
                            with self._runtime_lock:
                                self._inflight_handles[run_id] = (provider, handle)
                            try:
                                output, attempt_exc, timed_out = self._await_provider_with_polling(
                                    provider=provider,
                                    handle=handle,
                                    timeout=remaining_timeout,
                                    cancel_event=cancel_event,
                                )
                            finally:
                                with self._runtime_lock:
                                    self._inflight_handles.pop(run_id, None)
                if timed_out:
                    break
                if attempt_exc is None:
                    last_exc = None
                    break

                last_exc = attempt_exc
                # Non-retryable error — stop immediately
                if not attempt_exc.retryable:
                    break
                # Retryable codes filter — stop if code not in allowed set
                if retryable_codes and attempt_exc.code not in retryable_codes:
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
                        error=str(attempt_exc),
                        error_code=attempt_exc.code,
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
                redacted_input = _redact(input_payload)
                if timeout_output is not None:
                    # Spec §9: on_timeout.out continues the run; treat as completed
                    # for routing, but mark synthetic=True in the log for audit.
                    redacted_timeout_output = _redact(timeout_output)
                    log_entry = {
                        "node": node_name,
                        "status": NodeStatus.TIMED_OUT.value,
                        "effective_status": NodeStatus.COMPLETED.value,
                        "synthetic": True,
                        "attempts": attempts_used,
                        "timestamp": ts,
                        "input": redacted_input,
                        "output": redacted_timeout_output,
                        "idempotency_key": idempotency_key,
                    }
                    sink.emit(_base_event(
                        event_type="node_timed_out",
                        status=NodeStatus.TIMED_OUT.value,
                        effective_status=NodeStatus.COMPLETED.value,
                        synthetic=True,
                        input=redacted_input,
                        output=redacted_timeout_output,
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
                    escalation_routes = self._escalation_routes(
                        policy,
                        node_name=node_name,
                        event_name="timeout",
                        attempts=max_attempts,
                        payload=input_payload,
                    )
                    log_entry = {
                        "node": node_name,
                        "status": NodeStatus.TIMED_OUT.value,
                        "attempts": attempts_used,
                        "timestamp": ts,
                        "input": redacted_input,
                        "idempotency_key": idempotency_key,
                    }
                    sink.emit(_base_event(
                        event_type="node_timed_out",
                        status=NodeStatus.TIMED_OUT.value,
                        input=redacted_input,
                        idempotency_key=idempotency_key,
                        timestamp=ts,
                    ))
                    return {
                        "node_outputs": {},
                        "node_statuses": {node_name: NodeStatus.TIMED_OUT.value},
                        "execution_log": [log_entry],
                        "failure_routes": escalation_routes,
                        "run_status": (
                            NodeStatus.FAILED.value
                            if not escalation_routes
                            else state.get("run_status", "running")
                        ),
                    }

            # ----------------------------------------------------------
            # Handle exhausted retries (ProviderError)
            # ----------------------------------------------------------
            if last_exc is not None:
                failure_routes_update: Dict[str, Dict[str, Any]] = {}
                recoverable = False
                force_fail = False
                for firing_edge in firing_edges:
                    on_failure = firing_edge.edge.on_failure
                    if on_failure is None:
                        continue
                    action = on_failure.action
                    if action == EdgeFailureAction.ROUTE and on_failure.to is not None:
                        failure_routes_update[on_failure.to] = input_payload
                        recoverable = True
                    elif action == EdgeFailureAction.NOTIFY and on_failure.node is not None:
                        failure_routes_update[on_failure.node] = {
                            **input_payload,
                            "__failure__": {
                                "node": node_name,
                                "code": last_exc.code,
                                "error": str(last_exc),
                            },
                        }
                        recoverable = True
                    elif action == EdgeFailureAction.FAIL:
                        force_fail = True

                if not force_fail:
                    escalation_routes = self._escalation_routes(
                        policy,
                        node_name=node_name,
                        event_name="failure",
                        attempts=max_attempts,
                        payload=input_payload,
                    )
                    if escalation_routes:
                        recoverable = True
                    failure_routes_update.update(escalation_routes)

                ts = _now_iso()
                redacted_input = _redact(input_payload)
                log_entry = {
                    "node": node_name,
                    "status": (
                        NodeStatus.CANCELLED.value
                        if last_exc.code == "cancelled"
                        else NodeStatus.FAILED.value
                    ),
                    "attempts": attempts_used,
                    "timestamp": ts,
                    "input": redacted_input,
                    "error": str(last_exc),
                    "idempotency_key": idempotency_key,
                }
                sink.emit(_base_event(
                    event_type="node_failed",
                    status=log_entry["status"],
                    input=redacted_input,
                    error=str(last_exc),
                    error_code=last_exc.code,
                    idempotency_key=idempotency_key,
                    timestamp=ts,
                ))
                return {
                    "node_outputs": {},
                    "node_statuses": {node_name: log_entry["status"]},
                    "execution_log": [log_entry],
                    "failure_routes": failure_routes_update,
                    "recoverable_failures": [node_name] if recoverable else [],
                    "run_status": (
                        NodeStatus.CANCELLED.value
                        if last_exc.code == "cancelled"
                        else (
                            NodeStatus.FAILED.value
                            if force_fail or not failure_routes_update
                            else state.get("run_status", "running")
                        )
                    ),
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
                        "run_status": NodeStatus.FAILED.value,
                    }

            # ----------------------------------------------------------
            # Success
            # ----------------------------------------------------------
            ts = _now_iso()
            redacted_input = _redact(input_payload)
            redacted_output = _redact(output)
            log_entry = {
                "node": node_name,
                "status": NodeStatus.COMPLETED.value,
                "attempts": attempts_used,
                "timestamp": ts,
                "input": redacted_input,
                "output": redacted_output,
                "idempotency_key": idempotency_key,
            }
            self._result_cache[idempotency_key] = output or {}
            sink.emit(_base_event(
                event_type="node_completed",
                status=NodeStatus.COMPLETED.value,
                input=redacted_input,
                output=redacted_output,
                idempotency_key=idempotency_key,
                timestamp=ts,
            ))
            return {
                "node_outputs": {node_name: output},
                "node_statuses": {node_name: NodeStatus.COMPLETED.value},
                "execution_log": [log_entry],
                "failure_routes": {},
                "run_status": state.get("run_status", "running"),
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
            "recoverable_failures": [],
            "run_status": "running",
        }
        with self._runtime_lock:
            self._cancel_events[run_id] = threading.Event()

        config = {"configurable": {"thread_id": run_id}}
        final_state = self._graph.invoke(initial_state, config=config)
        if self._ir.process.output:
            try:
                process_output = resolve_mapping(
                    {"__process_output__": self._ir.process.output},
                    final_state,
                    self._ir.process.trigger,
                )["__process_output__"]
            except Exception:
                process_output = None
            final_state["process_output"] = process_output
        if final_state.get("run_status") == "running":
            if NodeStatus.CANCELLED.value in final_state.get("node_statuses", {}).values():
                final_state["run_status"] = NodeStatus.CANCELLED.value
            elif {
                n
                for n, s in final_state.get("node_statuses", {}).items()
                if s == NodeStatus.FAILED.value
            } - set(final_state.get("recoverable_failures", [])):
                final_state["run_status"] = NodeStatus.FAILED.value
            else:
                final_state["run_status"] = NodeStatus.COMPLETED.value
        if self._ir.process.policy and self._ir.process.policy.audit:
            audit = self._ir.process.policy.audit
            audit_record = {
                "retention": audit.retain_run_logs_for,
                "export_to": audit.export_to,
                "tags": dict(audit.tags or {}),
                "emitted_at": _now_iso(),
            }
            self._sink.emit({
                "event_type": "run_audit",
                "run_id": run_id,
                "process_name": process_name,
                "node": "__process__",
                "timestamp": audit_record["emitted_at"],
                "status": final_state.get("run_status", "completed"),
                "tags": audit_record["tags"],
            })
            final_state["audit"] = audit_record
        with self._runtime_lock:
            self._cancel_events.pop(run_id, None)
            self._inflight_handles.pop(run_id, None)
        return final_state

    def cancel_run(self, run_id: str) -> bool:
        """Request cancellation of a currently executing run.

        Returns True if a run context was found and marked as cancelled.
        """
        with self._runtime_lock:
            event = self._cancel_events.get(run_id)
            if event is None:
                return False
            event.set()
            inflight = self._inflight_handles.get(run_id)
        if inflight is not None:
            provider, handle = inflight
            provider.cancel(handle)
        return True

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
