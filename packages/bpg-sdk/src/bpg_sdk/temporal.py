from __future__ import annotations

from typing import Iterable

from bpg_sdk.discovery import DiscoveredNode


def build_temporal_activity_registry(
    catalog: dict[tuple[str, str], DiscoveredNode] | Iterable[DiscoveredNode],
) -> dict[str, DiscoveredNode]:
    """Expose discovered nodes under stable activity keys for Temporal bootstrap."""

    if isinstance(catalog, dict):
        nodes = catalog.values()
    else:
        nodes = catalog
    return {
        f"{node.manifest.package}:{node.manifest.node_id}": node
        for node in nodes
    }
