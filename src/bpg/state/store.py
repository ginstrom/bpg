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
from datetime import datetime, timezone
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
        deployments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist a deployed process definition.

        Args:
            process: The Process model to save.
            deployments: Optional deployment artifact metadata keyed by node
                name.  Each value is a dict with ``provider_id`` and
                ``artifacts`` keys.  Persisted verbatim under the
                ``deployments`` key in the record.

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

        # Load existing record to get the current version and increment it
        existing_version = 0
        if record_path.exists():
            try:
                with open(record_path, "r") as f:
                    existing = yaml.safe_load(f)
                    if existing and isinstance(existing.get("version"), int):
                        existing_version = existing["version"]
            except Exception:
                pass

        record = {
            "hash": definition_hash,
            "version": existing_version + 1,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "definition": pure_data,
            "deployments": deployments if deployments is not None else {},
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

    def load_record(self, process_name: str) -> Optional[Dict[str, Any]]:
        """Load the full raw state record for a process by name.

        Returns the complete record dict including ``hash``, ``version``,
        ``applied_at``, ``definition``, and ``deployments``, or ``None`` if no
        record exists for the given name.

        Args:
            process_name: The process name (used to construct the filename).

        Returns:
            The raw record dict, or ``None`` if not found.

        Raises:
            StateStoreError: On filesystem read failure.
        """
        record_path = self._processes_dir / f"{process_name}.yaml"
        if not record_path.exists():
            return None

        try:
            with open(record_path, "r") as f:
                record = yaml.safe_load(f)
                return record if record else None
        except Exception as e:
            raise StateStoreError(f"Failed to load record for {process_name}: {e}")

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
        self._ensure_dirs()
        run_dir = self._runs_dir / run_id
        if run_dir.exists():
            raise StateStoreError(f"Run {run_id} already exists")
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "nodes").mkdir(exist_ok=True)
        record = {
            "run_id": run_id,
            "process_name": process_name,
            "status": "running",
            "started_at": datetime.now(timezone.utc).isoformat(),
            "input": input_payload,
        }
        try:
            with open(run_dir / "run.yaml", "w") as f:
                yaml.safe_dump(record, f, sort_keys=False)
        except Exception as e:
            raise StateStoreError(f"Failed to create run {run_id}: {e}")

    def load_run(self, run_id: str) -> Optional[Dict[str, Any]]:
        """Load a run record by ID.

        Returns:
            The run record dict, or ``None`` if not found.
        """
        path = self._runs_dir / run_id / "run.yaml"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise StateStoreError(f"Failed to load run {run_id}: {e}")

    def update_run(self, run_id: str, updates: Dict[str, Any]) -> None:
        """Merge updates into an existing run record.

        Args:
            run_id: The run to update.
            updates: Dict of fields to set/overwrite.

        Raises:
            StateStoreError: If the run does not exist or write fails.
        """
        path = self._runs_dir / run_id / "run.yaml"
        if not path.exists():
            raise StateStoreError(f"Run {run_id} not found")
        try:
            with open(path) as f:
                record = yaml.safe_load(f) or {}
            record.update(updates)
            with open(path, "w") as f:
                yaml.safe_dump(record, f, sort_keys=False)
        except StateStoreError:
            raise
        except Exception as e:
            raise StateStoreError(f"Failed to update run {run_id}: {e}")

    def list_runs(self, process_name: Optional[str] = None) -> list[Dict[str, Any]]:
        """List all run records, optionally filtered by process name.

        Returns:
            List of run record dicts sorted by start time descending.
        """
        if not self._runs_dir.exists():
            return []
        runs = []
        for run_dir in self._runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            path = run_dir / "run.yaml"
            if not path.exists():
                continue
            try:
                with open(path) as f:
                    record = yaml.safe_load(f)
                if record:
                    if process_name is None or record.get("process_name") == process_name:
                        runs.append(record)
            except Exception:
                pass
        runs.sort(key=lambda r: r.get("started_at", ""), reverse=True)
        return runs

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
        run_dir = self._runs_dir / run_id
        if not run_dir.exists():
            raise StateStoreError(f"Run {run_id} does not exist")
        nodes_dir = run_dir / "nodes"
        nodes_dir.mkdir(exist_ok=True)
        try:
            with open(nodes_dir / f"{node_name}.yaml", "w") as f:
                yaml.safe_dump(record, f, sort_keys=False)
        except Exception as e:
            raise StateStoreError(f"Failed to save node record {run_id}/{node_name}: {e}")

    def load_node_record(self, run_id: str, node_name: str) -> Optional[Dict[str, Any]]:
        """Load a single node execution record.

        Returns:
            The node record dict, or ``None`` if not found.
        """
        path = self._runs_dir / run_id / "nodes" / f"{node_name}.yaml"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise StateStoreError(f"Failed to load node record {run_id}/{node_name}: {e}")

    # ------------------------------------------------------------------
    # Interaction state (human-in-the-loop pending/response records)
    # ------------------------------------------------------------------

    def _interaction_dir(self, idempotency_key: str) -> Path:
        return self._state_dir / "interactions" / idempotency_key

    def save_pending_interaction(self, idempotency_key: str, data: Dict[str, Any]) -> None:
        """Persist a pending interaction record (written before NodeInterrupt).

        Args:
            idempotency_key: Pre-computed idempotency key for this invocation.
            data: Metadata dict (run_id, node_name, process_name, channel, message_ts, …).

        Raises:
            StateStoreError: On filesystem write failure.
        """
        d = self._interaction_dir(idempotency_key)
        try:
            d.mkdir(parents=True, exist_ok=True)
            record = {"idempotency_key": idempotency_key, "created_at": datetime.now(timezone.utc).isoformat(), **data}
            with open(d / "pending.yaml", "w") as f:
                yaml.safe_dump(record, f, sort_keys=False)
        except Exception as e:
            raise StateStoreError(f"Failed to save pending interaction {idempotency_key}: {e}")

    def load_pending_interaction(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """Load a pending interaction record.

        Returns:
            The record dict, or ``None`` if not found.
        """
        path = self._interaction_dir(idempotency_key) / "pending.yaml"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                return yaml.safe_load(f)
        except Exception as e:
            raise StateStoreError(f"Failed to load pending interaction {idempotency_key}: {e}")

    def save_interaction_response(self, idempotency_key: str, response: Dict[str, Any]) -> None:
        """Persist the human response for a pending interaction.

        Should be called by the external callback handler (e.g. Slack webhook)
        before resuming the graph.

        Args:
            idempotency_key: Pre-computed idempotency key for this invocation.
            response: The human response payload (e.g. ``{"approved": True}``).

        Raises:
            StateStoreError: On filesystem write failure.
        """
        d = self._interaction_dir(idempotency_key)
        try:
            d.mkdir(parents=True, exist_ok=True)
            record = {"idempotency_key": idempotency_key, "responded_at": datetime.now(timezone.utc).isoformat(), "response": response}
            with open(d / "response.yaml", "w") as f:
                yaml.safe_dump(record, f, sort_keys=False)
        except Exception as e:
            raise StateStoreError(f"Failed to save interaction response {idempotency_key}: {e}")

    def load_interaction_response(self, idempotency_key: str) -> Optional[Dict[str, Any]]:
        """Load a human response for an interaction.

        Returns:
            The response payload dict, or ``None`` if no response yet.
        """
        path = self._interaction_dir(idempotency_key) / "response.yaml"
        if not path.exists():
            return None
        try:
            with open(path) as f:
                record = yaml.safe_load(f)
                return record.get("response") if record else None
        except Exception as e:
            raise StateStoreError(f"Failed to load interaction response {idempotency_key}: {e}")
