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

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from bpg.models.schema import Process


class StateStoreError(Exception):
    """Raised on state persistence or retrieval errors."""


class StateStore:
    """Filesystem-backed BPG state store.

    Args:
        state_dir: Root directory for state files.  Created if absent.
    """

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir
        self._processes_dir = state_dir / "processes"
        self._runs_dir = state_dir / "runs"

    def _ensure_dirs(self) -> None:
        self._processes_dir.mkdir(parents=True, exist_ok=True)
        self._runs_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Process state (deployed definitions)
    # ------------------------------------------------------------------

    def save_process(
        self,
        process: Process,
    ) -> str:
        """Persist a deployed process definition.

        Args:
            process: The Process model to save.

        Returns:
            SHA-256 hash of the serialized process definition.

        Raises:
            StateStoreError: On filesystem write failure.
        """
        self._ensure_dirs()
        process_name = process.metadata.name if process.metadata else "default"
        record_path = self._processes_dir / f"{process_name}.yaml"
        
        # Serialize to dict using json-safe values to avoid Python-specific YAML tags (like Enums)
        # model_dump_json followed by json.loads is a reliable way to get a "pure" dict
        import json
        pure_data = json.loads(process.model_dump_json(by_alias=True, exclude_none=True))
        
        # Calculate hash for change detection
        content = yaml.dump(pure_data, sort_keys=True)
        definition_hash = hashlib.sha256(content.encode()).hexdigest()
        
        record = {
            "hash": definition_hash,
            "definition": pure_data,
        }
        
        try:
            with open(record_path, "w") as f:
                # Use safe_dump to ensure no Python-specific tags are written
                yaml.safe_dump(record, f, sort_keys=False)
            return definition_hash
        except Exception as e:
            raise StateStoreError(f"Failed to save process {process_name}: {e}")

    def load_process(self, process_name: str) -> Optional[Process]:
        """Load a deployed process definition by name.

        Returns:
            The Process model, or ``None`` if not found.
        """
        record_path = self._processes_dir / f"{process_name}.yaml"
        if not record_path.exists():
            return None
            
        try:
            with open(record_path, "r") as f:
                record = yaml.safe_load(f)
                if not record or "definition" not in record:
                    return None
                return Process.model_validate(record["definition"])
        except Exception as e:
            raise StateStoreError(f"Failed to load process {process_name}: {e}")

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
        # TODO: implement in Phase 3
        raise NotImplementedError("StateStore.create_run not yet implemented")

    def load_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Load a run record by ID.

        Returns:
            The run record dict, or ``None`` if not found.
        """
        # TODO: implement in Phase 3
        raise NotImplementedError("StateStore.load_run not yet implemented")

    def list_runs(self, process_name: Optional[str] = None) -> list[Dict[str, Any]]:
        """List all run records, optionally filtered by process name.

        Returns:
            List of run record dicts sorted by start time descending.
        """
        # TODO: implement in Phase 3
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
        # TODO: implement in Phase 3
        raise NotImplementedError("StateStore.save_node_record not yet implemented")

    def load_node_record(self, run_id: str, node_name: str) -> Optional[Dict[str, Any]]:
        """Load a single node execution record.

        Returns:
            The node record dict, or ``None`` if not found.
        """
        # TODO: implement in Phase 3
        raise NotImplementedError("StateStore.load_node_record not yet implemented")
