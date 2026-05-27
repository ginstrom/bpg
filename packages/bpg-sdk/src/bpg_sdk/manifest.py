from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SideEffects(str, Enum):
    NONE = "none"
    READS = "reads"
    WRITES = "writes"
    EXTERNAL = "external"


class Idempotency(str, Enum):
    IDEMPOTENT = "idempotent"
    NON_IDEMPOTENT = "non_idempotent"
    CONDITIONAL = "conditional"


class RetrySafety(str, Enum):
    SAFE = "safe"
    UNSAFE = "unsafe"
    CONDITIONAL = "conditional"


class ObservabilitySupport(str, Enum):
    SUPPORTED = "supported"
    REQUIRED = "required"
    NONE = "none"


class NodeManifest(BaseModel):
    """Canonical framework metadata emitted by SDK-authored nodes."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    package: str = Field(
        pattern=r"^bpg\.nodes(?:\.[a-z0-9_]+)+@v[0-9]+$",
        description="Stable package identifier consumed by process spec v2.",
    )
    node_id: str = Field(
        pattern=r"^[a-zA-Z][a-zA-Z0-9_.-]*$",
        description="Exported node identifier within the package.",
    )
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
    side_effects: SideEffects = SideEffects.NONE
    idempotency: Idempotency = Idempotency.CONDITIONAL
    retry_safety: RetrySafety = RetrySafety.CONDITIONAL
    observability: ObservabilitySupport = ObservabilitySupport.SUPPORTED
