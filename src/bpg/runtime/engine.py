"""BPG execution engine.

The engine is responsible for driving a process run from trigger through to
completion.  It is event-driven: nodes become eligible for execution as their
upstream dependencies complete and their incoming edge conditions are met.

Each process run has:
    - A unique, globally unique ``run_id``
    - An immutable, append-only execution log
    - A per-node execution record (status, input, output, timestamps,
      idempotency key)

Idempotency (§8):
    idempotency_key = sha256(run_id + ":" + node_name + ":" + canonical_json(stable_input_fields))
"""

from __future__ import annotations

from typing import Any, Dict

from bpg.models.schema import Process


class EngineError(Exception):
    """Raised when the engine encounters an unrecoverable execution error."""


class Engine:
    """Event-driven execution engine for a single BPG process.

    Usage (once implemented)::

        engine = Engine(process=process, state_store=store)
        run_id = engine.trigger(input_payload={"title": "Login broken", ...})
        engine.await_run(run_id)

    Args:
        process: The compiled and validated ``Process`` definition.
        state_store: A ``StateStore`` instance for persisting run records.
    """

    def __init__(self, process: Process, state_store: Any) -> None:
        self._process = process
        self._state_store = state_store

    def trigger(self, input_payload: Dict[str, Any]) -> str:
        """Start a new process run and return the unique ``run_id``.

        Args:
            input_payload: The initial input conforming to the trigger node's
                           ``in`` type.

        Returns:
            A globally unique run identifier.

        Raises:
            EngineError: If the input payload fails type validation.
        """
        import uuid
        from datetime import datetime, timezone
        from bpg.compiler.ir import compile_process
        from bpg.compiler.validator import validate_process
        from bpg.providers import PROVIDER_REGISTRY
        from bpg.runtime.langgraph_runtime import LangGraphRuntime

        run_id = str(uuid.uuid4())
        process_name = (
            self._process.metadata.name if self._process.metadata else "default"
        )

        # Compile IR (raises ValidationError if invalid)
        validate_process(self._process)
        ir = compile_process(self._process)

        # Persist initial run record
        self._state_store.create_run(run_id, process_name, input_payload)

        # Build providers from registry (skip any that need special init args)
        providers: Dict[str, Any] = {}
        for pid, cls in PROVIDER_REGISTRY.items():
            try:
                providers[pid] = cls()
            except Exception:
                pass

        # Execute
        runtime = LangGraphRuntime(ir=ir, providers=providers)
        final_state = runtime.run(input_payload=input_payload, run_id=run_id)

        # Persist per-node records from execution log
        for entry in final_state.get("execution_log", []):
            node_name = entry.get("node")
            if node_name:
                self._state_store.save_node_record(run_id, node_name, entry)

        # Determine run status from final node statuses
        from bpg.models.schema import NodeStatus
        failed_nodes = [
            n for n, s in final_state.get("node_statuses", {}).items()
            if s == NodeStatus.FAILED.value
        ]
        failure_routes_used = set(final_state.get("failure_routes", {}).keys())
        # Run is "failed" if any node failed without an established failure route
        unhandled_failures = [n for n in failed_nodes if n not in failure_routes_used]
        run_status = "failed" if unhandled_failures else "completed"

        self._state_store.update_run(run_id, {
            "status": run_status,
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

        return run_id

    def step(self, run_id: str) -> None:
        """Advance a run by evaluating and dispatching all ready nodes.

        A node is "ready" when all of its upstream dependencies have a terminal
        status (completed, skipped, failed, timed_out) and at least one incoming
        edge condition is satisfied.

        Args:
            run_id: The run to advance.
        """
        # The LangGraph runtime executes synchronously inside trigger().
        # step() is a no-op for the synchronous runtime.
        pass

    def _compute_idempotency_key(self, run_id: str, node_name: str, input_payload: Dict[str, Any]) -> str:
        """Compute the idempotency key for a node invocation.

        key = sha256(run_id + ":" + node_name + ":" + canonical_json(stable_input_fields))
        """
        from bpg.providers.base import compute_idempotency_key
        return compute_idempotency_key(run_id, node_name, input_payload)
