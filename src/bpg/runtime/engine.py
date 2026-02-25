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
        # TODO: implement
        #   1. Validate input_payload against trigger node's in type
        #   2. Generate run_id (UUID4)
        #   3. Persist initial run record via state_store
        #   4. Enqueue trigger node for execution
        #   5. Return run_id
        raise NotImplementedError("Engine.trigger not yet implemented")

    def step(self, run_id: str) -> None:
        """Advance a run by evaluating and dispatching all ready nodes.

        A node is "ready" when all of its upstream dependencies have a terminal
        status (completed, skipped, failed, timed_out) and at least one incoming
        edge condition is satisfied.

        Args:
            run_id: The run to advance.
        """
        # TODO: implement event loop step
        raise NotImplementedError("Engine.step not yet implemented")

    def _compute_idempotency_key(self, run_id: str, node_name: str, input_payload: Dict[str, Any]) -> str:
        """Compute the idempotency key for a node invocation.

        key = sha256(run_id + ":" + node_name + ":" + canonical_json(stable_input_fields))
        """
        # TODO: implement
        raise NotImplementedError("Engine._compute_idempotency_key not yet implemented")
