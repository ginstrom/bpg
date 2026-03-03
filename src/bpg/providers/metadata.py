"""Provider metadata contract for discovery and agent tooling."""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProviderSideEffects(str, Enum):
    NONE = "none"
    READS = "reads"
    WRITES = "writes"
    EXTERNAL = "external"


class ProviderIdempotency(str, Enum):
    YES = "yes"
    NO = "no"
    CONDITIONAL = "conditional"


class ProviderLatencyClass(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ProviderExample(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    config: dict[str, Any] = Field(default_factory=dict)
    input: dict[str, Any] = Field(default_factory=dict)


class ProviderMetadata(BaseModel):
    """Machine-readable provider description used by `bpg providers` commands."""

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    side_effects: ProviderSideEffects = ProviderSideEffects.NONE
    idempotency: ProviderIdempotency = ProviderIdempotency.CONDITIONAL
    latency_class: ProviderLatencyClass = ProviderLatencyClass.MEDIUM
    examples: list[ProviderExample] = Field(default_factory=list)


def default_provider_metadata(provider_id: str, provider_cls: type[Any]) -> ProviderMetadata:
    """Create a safe default metadata payload for providers without explicit metadata."""
    description = (
        (provider_cls.__doc__ or "").strip().splitlines()[0]
        if getattr(provider_cls, "__doc__", None)
        else f"Provider implementation for {provider_id}."
    )
    return ProviderMetadata(
        name=provider_id,
        description=description,
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        side_effects=ProviderSideEffects.EXTERNAL,
        idempotency=ProviderIdempotency.CONDITIONAL,
        latency_class=ProviderLatencyClass.MEDIUM,
        examples=[
            ProviderExample(
                title="default",
                config={},
                input={},
            )
        ],
    )
