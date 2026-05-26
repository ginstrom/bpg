from __future__ import annotations

from dataclasses import dataclass, field
import json
from typing import Any, Protocol
import uuid


@dataclass(slots=True, frozen=True)
class CheckpointPolicy:
    """Checkpoint settings for LangGraph-backed node execution."""

    max_inline_bytes: int = 65_536
    spill_to_blob: bool = True


@dataclass(slots=True, frozen=True)
class LangGraphNodeMetadata:
    """Framework-visible metadata for a LangGraph-backed node."""

    engine: str = "langgraph"
    checkpoint: CheckpointPolicy = field(default_factory=CheckpointPolicy)
    tool_registry: list[str] = field(default_factory=list)
    structured_output_schema: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class LangGraphStepResult:
    """Result of a single deterministic node step."""

    state: dict[str, Any]
    completed: bool
    output: dict[str, Any] | None = None


@dataclass(slots=True, frozen=True)
class LangGraphNodeCheckpoint:
    """Persisted checkpoint for node-local LangGraph state."""

    checkpoint_id: str
    run_id: str
    step_index: int
    state: dict[str, Any] | None = None
    blob_key: str | None = None


@dataclass(slots=True, frozen=True)
class LangGraphNodeRunResult:
    """Return payload for a node workflow run or resume."""

    completed: bool
    state: dict[str, Any]
    output: dict[str, Any] | None = None
    checkpoint: LangGraphNodeCheckpoint | None = None


class LangGraphBehavior(Protocol):
    """Contract for node-local LangGraph behavior under Temporal orchestration."""

    def step(
        self,
        *,
        state: dict[str, Any],
        metadata: LangGraphNodeMetadata,
        run_id: str,
        step_index: int,
    ) -> LangGraphStepResult:
        """Advance one deterministic node step."""


class CheckpointBlobStore(Protocol):
    """Blob store for checkpoint payloads that exceed inline size limits."""

    def put_json(self, payload: dict[str, Any]) -> str:
        """Persist a JSON-serializable payload and return a stable key."""

    def get_json(self, key: str) -> dict[str, Any]:
        """Load a previously persisted JSON payload."""


class InMemoryCheckpointBlobStore:
    """Simple blob store used by unit tests and local workflow simulations."""

    def __init__(self) -> None:
        self._payloads: dict[str, dict[str, Any]] = {}

    def put_json(self, payload: dict[str, Any]) -> str:
        key = f"blob-{uuid.uuid4()}"
        self._payloads[key] = json.loads(json.dumps(payload))
        return key

    def get_json(self, key: str) -> dict[str, Any]:
        return json.loads(json.dumps(self._payloads[key]))
