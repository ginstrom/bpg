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
                events.jsonl             # append-only execution event log
                nodes/
                    <node-name>.yaml     # per-node execution record

The store is append-only for run records.  Process records are overwritten
on each apply.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
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

    @staticmethod
    def _artifact_checksum(artifacts: Dict[str, Any]) -> str:
        payload = json.dumps(artifacts, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode()).hexdigest()

    @staticmethod
    def _parse_duration_seconds(value: Optional[str]) -> Optional[float]:
        if not value:
            return None
        m = re.match(r"^(\d+(?:\.\d+)?)\s*(ms|s|m|h|d)$", value.strip())
        if not m:
            return None
        amount = float(m.group(1))
        unit = m.group(2)
        factors = {"ms": 0.001, "s": 1.0, "m": 60.0, "h": 3600.0, "d": 86400.0}
        return amount * factors[unit]

    # ------------------------------------------------------------------
    # Process state (deployed definitions)
    # ------------------------------------------------------------------

    def save_process(
        self,
        ir: "ExecutionIR",
        deployments: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist a deployed process definition and its IR artifacts.

        Args:
            ir: The compiled ExecutionIR to save.
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
        process = ir.process
        process_name = process.metadata.name if process.metadata else "default"
        record_path = self._processes_dir / f"{process_name}.yaml"

        # Serialize to dict using json-safe values to avoid Python-specific YAML tags (like Enums)
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

        normalized_deployments: Dict[str, Any] = {}
        for node_name, dep in (deployments or {}).items():
            dep_copy = dict(dep)
            artifacts = dep_copy.get("artifacts", {}) or {}
            dep_copy["artifacts"] = artifacts
            dep_copy["artifact_checksum"] = self._artifact_checksum(artifacts)
            normalized_deployments[node_name] = dep_copy

        record = {
            "hash": definition_hash,
            "version": existing_version + 1,
            "applied_at": datetime.now(timezone.utc).isoformat(),
            "process_version": process.metadata.version if process.metadata else None,
            "definition": pure_data,
            "deployments": normalized_deployments,
            "topological_order": ir.topological_order,
            "node_type_pins": {
                node_name: node.node_type for node_name, node in process.nodes.items()
            },
            "type_pins": sorted(process.types.keys()),
            "type_checksums": {
                type_name: hashlib.sha256(
                    json.dumps(
                        type_def.root,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                for type_name, type_def in process.types.items()
            },
            "node_type_checksums": {
                node_type_name: hashlib.sha256(
                    json.dumps(
                        node_type.model_dump(by_alias=True, exclude_none=True),
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode()
                ).hexdigest()
                for node_type_name, node_type in process.node_types.items()
            },
            "ir_checksum": hashlib.sha256(
                json.dumps(
                    {
                        "topological_order": ir.topological_order,
                        "resolved_nodes": sorted(ir.resolved_nodes.keys()),
                        "resolved_edges": sorted(
                            f"{e.source.name}->{e.target.name}:{e.edge.when or ''}"
                            for e in ir.resolved_edges
                        ),
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest(),
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

    def verify_artifact_checksums(self, process_name: str) -> bool:
        """Verify persisted deployment artifact checksums for a process record."""
        record = self.load_record(process_name)
        if not record:
            return True
        deployments = record.get("deployments", {}) or {}
        for node_name, dep in deployments.items():
            artifacts = dep.get("artifacts", {}) or {}
            expected = dep.get("artifact_checksum")
            if expected is None:
                return False
            actual = self._artifact_checksum(artifacts)
            if actual != expected:
                raise StateStoreError(
                    f"Artifact checksum mismatch for node {node_name}: expected {expected}, got {actual}"
                )
        return True

    # ------------------------------------------------------------------
    # Run state (execution records)
    # ------------------------------------------------------------------

    def create_run(
        self,
        run_id: str,
        process_name: str,
        input_payload: Dict[str, Any],
        process_snapshot: Optional[Dict[str, Any]] = None,
    ) -> None:
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
        if process_snapshot:
            record.update(process_snapshot)
        try:
            with open(run_dir / "run.yaml", "w") as f:
                yaml.safe_dump(record, f, sort_keys=False)
            (run_dir / "events.jsonl").touch(exist_ok=True)
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

    def prune_runs(
        self,
        *,
        process_name: Optional[str] = None,
        older_than: Optional[str] = None,
        statuses: Optional[set[str]] = None,
        dry_run: bool = False,
    ) -> list[str]:
        """Delete run records matching pruning filters.

        Args:
            process_name: Optional process name filter.
            older_than: Optional duration (e.g. ``30d``) based on ``started_at``.
            statuses: Optional allowed set of run statuses to prune.
            dry_run: When True, only returns candidate run IDs.

        Returns:
            List of run IDs that matched the pruning criteria.
        """
        retention_seconds = self._parse_duration_seconds(older_than)
        cutoff = None
        if retention_seconds is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - retention_seconds

        matched: list[str] = []
        for run in self.list_runs(process_name=process_name):
            run_id = run.get("run_id")
            if not isinstance(run_id, str) or not run_id:
                continue
            if statuses and str(run.get("status", "")) not in statuses:
                continue
            if cutoff is not None:
                started_at = run.get("started_at")
                if not isinstance(started_at, str):
                    continue
                try:
                    started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if started_dt.timestamp() >= cutoff:
                    continue
            matched.append(run_id)

        if not dry_run:
            for run_id in matched:
                shutil.rmtree(self._runs_dir / run_id, ignore_errors=True)
        return matched

    def save_node_record(
        self,
        run_id: str,
        node_name: str,
        record: Dict[str, Any],
    ) -> None:
        """Append or update a node execution record within a run.

        Existing snapshots are merged (append-only semantics preserved by the
        separate per-run events log).

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
            node_path = nodes_dir / f"{node_name}.yaml"
            existing: Dict[str, Any] = {}
            if node_path.exists():
                with open(node_path) as f:
                    existing = yaml.safe_load(f) or {}
            merged = {**existing, **record}
            with open(node_path, "w") as f:
                yaml.safe_dump(merged, f, sort_keys=False)
        except Exception as e:
            raise StateStoreError(f"Failed to save node record {run_id}/{node_name}: {e}")

    def append_execution_event(self, run_id: str, event: Dict[str, Any]) -> None:
        """Append a single execution event to the immutable run event log."""
        run_dir = self._runs_dir / run_id
        if not run_dir.exists():
            raise StateStoreError(f"Run {run_id} does not exist")
        events_path = run_dir / "events.jsonl"
        try:
            with open(events_path, "a") as f:
                f.write(json.dumps(event, sort_keys=True) + "\n")
        except Exception as e:
            raise StateStoreError(f"Failed to append execution event for run {run_id}: {e}")

    def load_execution_log(self, run_id: str) -> list[Dict[str, Any]]:
        """Load append-only execution events for a run in write order."""
        events_path = self._runs_dir / run_id / "events.jsonl"
        if not events_path.exists():
            return []
        out: list[Dict[str, Any]] = []
        try:
            with open(events_path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    out.append(json.loads(line))
            return out
        except Exception as e:
            raise StateStoreError(f"Failed to load execution log for run {run_id}: {e}")

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

    def list_node_records(self, run_id: str) -> Dict[str, Dict[str, Any]]:
        """Load all node execution records for a run keyed by node name."""
        nodes_dir = self._runs_dir / run_id / "nodes"
        if not nodes_dir.exists():
            return {}
        records: Dict[str, Dict[str, Any]] = {}
        for node_file in nodes_dir.glob("*.yaml"):
            try:
                with open(node_file) as f:
                    rec = yaml.safe_load(f) or {}
                records[node_file.stem] = rec
            except Exception as e:
                raise StateStoreError(f"Failed to load node record {run_id}/{node_file.stem}: {e}")
        return records

    def apply_audit_policy(
        self,
        *,
        run_id: str,
        process_name: str,
        audit_record: Dict[str, Any],
        run_status: str,
        execution_log: list[Dict[str, Any]],
    ) -> None:
        """Apply retention/export policy for a completed run."""
        retention = audit_record.get("retention")
        export_to = audit_record.get("export_to")

        retention_seconds = self._parse_duration_seconds(retention)
        if retention_seconds is not None:
            cutoff = datetime.now(timezone.utc).timestamp() - retention_seconds
            for run in self.list_runs(process_name=process_name):
                rid = run.get("run_id")
                if not rid or rid == run_id:
                    continue
                started_at = run.get("started_at")
                if not isinstance(started_at, str):
                    continue
                try:
                    started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                except ValueError:
                    continue
                if started_dt.timestamp() < cutoff:
                    shutil.rmtree(self._runs_dir / rid, ignore_errors=True)

        if isinstance(export_to, str) and export_to.strip():
            if export_to.startswith("file://"):
                path = Path(export_to[len("file://"):])
            elif export_to.startswith("file:"):
                path = Path(export_to[len("file:"):])
            else:
                safe = re.sub(r"[^a-zA-Z0-9_.-]+", "_", export_to)
                path = self._state_dir / "exports" / f"{safe}.jsonl"
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "run_id": run_id,
                "process_name": process_name,
                "status": run_status,
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "audit": audit_record,
                "execution_log": execution_log,
            }
            with open(path, "a") as f:
                f.write(json.dumps(payload, sort_keys=True) + "\n")

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
