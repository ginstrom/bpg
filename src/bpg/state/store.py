"""BPG state store — filesystem-backed persistence for process and run state.

The default implementation uses a directory on the local filesystem (typically
``.bpg-state/``) with YAML files for human readability and git-friendliness.

State layout::

    .bpg-state/
        processes/
            <process-name>.yaml          # deployed process definition + IR hash
        runs/
            <run-id>/
                run.yaml                 # run metadata (status, timestamps)
                nodes/
                    <node-name>.yaml     # per-node execution record

The store is append-only for run records.  Process records are overwritten
on each apply.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional


class StateStoreError(Exception):
    """Raised on state persistence or retrieval errors."""


class StateStore:
    """Filesystem-backed BPG state store.

    Args:
        state_dir: Root directory for state files.  Created if absent.

    Usage (once implemented)::

        store = StateStore(state_dir=Path(".bpg-state"))
        store.save_process(process_name="bug-triage", definition_hash="abc123", ir={...})
        run_record = store.load_run(run_id="run-uuid")
    """

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir

    # ------------------------------------------------------------------
    # Process state (deployed definitions)
    # ------------------------------------------------------------------

    def save_process(
        self,
        process_name: str,
        definition_hash: str,
        ir: Dict[str, Any],
    ) -> None:
        """Persist a deployed process definition and its IR hash.

        Args:
            process_name: Unique name of the process.
            definition_hash: SHA-256 hash of the serialized process definition.
            ir: Execution Intermediate Representation dict.

        Raises:
            StateStoreError: On filesystem write failure.
        """
        # TODO: implement
        raise NotImplementedError("StateStore.save_process not yet implemented")

    def load_process(self, process_name: str) -> Optional[Dict[str, Any]]:
        """Load a deployed process record by name.

        Returns:
            The persisted process record dict, or ``None`` if not found.
        """
        # TODO: implement
        raise NotImplementedError("StateStore.load_process not yet implemented")

    # ------------------------------------------------------------------
    # Run state (execution records)
    # ------------------------------------------------------------------

    def create_run(self, run_id: str, process_name: str, input_payload: Dict[str, Any]) -> None:
        """Create a new run record.  Must be called before any node records.

        Args:
            run_id: Globally unique run identifier (UUID4).
            process_name: Name of the process being executed.
            input_payload: The trigger input payload.

        Raises:
            StateStoreError: If the run_id already exists.
        """
        # TODO: implement
        raise NotImplementedError("StateStore.create_run not yet implemented")

    def load_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Load a run record by ID.

        Returns:
            The run record dict, or ``None`` if not found.
        """
        # TODO: implement
        raise NotImplementedError("StateStore.load_run not yet implemented")

    def list_runs(self, process_name: Optional[str] = None) -> list[Dict[str, Any]]:
        """List all run records, optionally filtered by process name.

        Returns:
            List of run record dicts sorted by start time descending.
        """
        # TODO: implement
        raise NotImplementedError("StateStore.list_runs not yet implemented")

    def save_node_record(
        self,
        run_id: str,
        node_name: str,
        record: Dict[str, Any],
    ) -> None:
        """Append or update a node execution record within a run.

        The store is append-only: existing records are not deleted, only updated
        with new status fields (e.g. completed_at, output).

        Args:
            run_id: The run this node belongs to.
            node_name: The node instance name.
            record: Dict containing status, input, output, timestamps, etc.

        Raises:
            StateStoreError: If the run_id does not exist.
        """
        # TODO: implement
        raise NotImplementedError("StateStore.save_node_record not yet implemented")

    def load_node_record(self, run_id: str, node_name: str) -> Optional[Dict[str, Any]]:
        """Load a single node execution record.

        Returns:
            The node record dict, or ``None`` if not found.
        """
        # TODO: implement
        raise NotImplementedError("StateStore.load_node_record not yet implemented")
