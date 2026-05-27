from __future__ import annotations

from abc import ABC, abstractmethod
from functools import update_wrapper
from typing import Any, Callable

from bpg_sdk.manifest import (
    Idempotency,
    NodeManifest,
    ObservabilitySupport,
    RetrySafety,
    SideEffects,
)


class Node(ABC):
    """Base class for stateful or advanced node implementations."""

    manifest: NodeManifest

    @abstractmethod
    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Execute the node against a structured payload."""


class FunctionNode(Node):
    """Function-backed node adapter returned by the `@node` decorator."""

    def __init__(self, func: Callable[[dict[str, Any]], dict[str, Any]], manifest: NodeManifest) -> None:
        self._func = func
        self.manifest = manifest
        update_wrapper(self, func)

    def __call__(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.run(payload)

    def run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._func(payload)


def node(
    *,
    package: str,
    node_id: str,
    input_schema: dict[str, Any],
    output_schema: dict[str, Any],
    capabilities: list[str] | None = None,
    side_effects: SideEffects = SideEffects.NONE,
    idempotency: Idempotency = Idempotency.CONDITIONAL,
    retry_safety: RetrySafety = RetrySafety.CONDITIONAL,
    observability: ObservabilitySupport = ObservabilitySupport.SUPPORTED,
) -> Callable[[Callable[[dict[str, Any]], dict[str, Any]]], FunctionNode]:
    """Declare a simple function node and attach canonical framework metadata."""

    manifest = NodeManifest(
        package=package,
        node_id=node_id,
        input_schema=input_schema,
        output_schema=output_schema,
        capabilities=capabilities or [],
        side_effects=side_effects,
        idempotency=idempotency,
        retry_safety=retry_safety,
        observability=observability,
    )

    def decorator(func: Callable[[dict[str, Any]], dict[str, Any]]) -> FunctionNode:
        return FunctionNode(func, manifest)

    return decorator
