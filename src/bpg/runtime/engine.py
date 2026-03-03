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

from datetime import datetime, timezone
from typing import Any, Dict

from bpg.models.schema import Process
from bpg.runtime.backends import get_backend


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

    def __init__(self, process: Process, state_store: Any, backend: str = "langgraph") -> None:
        self._process = process
        self._state_store = state_store
        self._backend_name = backend

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

        run_id = str(uuid.uuid4())
        process_name = (
            self._process.metadata.name if self._process.metadata else "default"
        )
        deployed_record = self._state_store.load_record(process_name)
        process_snapshot = {
            "process_version": (
                (deployed_record or {}).get("process_version")
                or (self._process.metadata.version if self._process.metadata else None)
            ),
            "process_hash": (deployed_record or {}).get("hash"),
            "process_record_version": (deployed_record or {}).get("version"),
        }

        # Persist initial run record, then execute immediately.
        self._state_store.create_run(
            run_id,
            process_name,
            input_payload,
            process_snapshot=process_snapshot,
            engine_backend=self._backend_name,
        )
        self._execute_run(
            run_id=run_id,
            input_payload=input_payload,
            backend_name=self._backend_name,
        )
        return run_id

    def step(self, run_id: str) -> None:
        """Advance a run by evaluating and dispatching all ready nodes.

        A node is "ready" when all of its upstream dependencies have a terminal
        status (completed, skipped, failed, timed_out) and at least one incoming
        edge condition is satisfied.

        Args:
            run_id: The run to advance.
        """
        run_record = self._state_store.load_run(run_id)
        if run_record is None:
            raise EngineError(f"Run {run_id!r} not found")

        status = run_record.get("status", "running")
        if status in {"completed", "cancelled"}:
            return

        input_payload = run_record.get("input", {})
        if not isinstance(input_payload, dict):
            raise EngineError(f"Run {run_id!r} has invalid input payload")

        # Replays the run idempotently using the same run_id so provider calls
        # can deduplicate external effects by idempotency key.
        backend_name = run_record.get("engine_backend", self._backend_name)
        self._execute_run(
            run_id=run_id,
            input_payload=input_payload,
            backend_name=backend_name,
        )

    def _execute_run(self, run_id: str, input_payload: Dict[str, Any], backend_name: str) -> None:
        cached_results: Dict[str, Dict[str, Any]] = {}
        for node_rec in self._state_store.list_node_records(run_id).values():
            if node_rec.get("status") != "completed":
                continue
            cache_key = node_rec.get("idempotency_key")
            cache_output = node_rec.get("output")
            if isinstance(cache_key, str) and isinstance(cache_output, dict):
                cached_results[cache_key] = cache_output

        try:
            backend = get_backend(str(backend_name))
        except ValueError as exc:
            raise EngineError(str(exc)) from exc

        final_state = backend.run(
            process=self._process,
            state_store=self._state_store,
            run_id=run_id,
            input_payload=input_payload,
            cached_results=cached_results,
        )

        for entry in final_state.get("execution_log", []):
            node_name = entry.get("node")
            self._state_store.append_execution_event(run_id, entry)
            if node_name:
                self._state_store.save_node_record(run_id, node_name, entry)

        run_status = final_state.get("run_status", "completed")
        updates = {
            "status": run_status,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "engine_backend": backend_name,
        }
        if "process_output" in final_state:
            updates["output"] = final_state["process_output"]
        self._state_store.update_run(run_id, updates)
        if "audit" in final_state and isinstance(final_state["audit"], dict):
            self._state_store.apply_audit_policy(
                run_id=run_id,
                process_name=(
                    self._process.metadata.name if self._process.metadata else "default"
                ),
                audit_record=final_state["audit"],
                run_status=run_status,
                execution_log=final_state.get("execution_log", []),
            )

    def _compute_idempotency_key(self, run_id: str, node_name: str, input_payload: Dict[str, Any]) -> str:
        """Compute the idempotency key for a node invocation.

        key = sha256(run_id + ":" + node_name + ":" + canonical_json(stable_input_fields))
        """
        from bpg.providers.base import compute_idempotency_key
        return compute_idempotency_key(run_id, node_name, input_payload)
