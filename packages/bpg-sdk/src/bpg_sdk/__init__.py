"""Public authoring and discovery APIs for installable BPG node packages."""

from bpg_sdk.authoring import FunctionNode, Node, node
from bpg_sdk.discovery import DiscoveredNode, DiscoveryError, discover_nodes
from bpg_sdk.langgraph import build_langgraph_registration
from bpg_sdk.manifest import (
    Idempotency,
    NodeManifest,
    ObservabilitySupport,
    RetrySafety,
    SideEffects,
)
from bpg_sdk.temporal import build_temporal_activity_registry

__all__ = [
    "DiscoveredNode",
    "DiscoveryError",
    "FunctionNode",
    "Idempotency",
    "Node",
    "NodeManifest",
    "ObservabilitySupport",
    "RetrySafety",
    "SideEffects",
    "build_langgraph_registration",
    "build_temporal_activity_registry",
    "discover_nodes",
    "node",
]
