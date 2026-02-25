"""BPG state layer — persistence and retrieval of process and run state.

The state store is the source of truth for:
    - Deployed process definition hashes and IR
    - Pinned node type and type versions
    - Provider artifact references and checksums
    - Per-run execution records (append-only)
    - Per-node execution records (status, input, output, timestamps)

State is persisted to the local filesystem under ``.bpg-state/`` by default.
Future backends (remote object storage, a database) can be added by
implementing the ``StateStore`` protocol.
"""

from bpg.state.store import StateStore, StateStoreError

__all__ = ["StateStore", "StateStoreError"]
