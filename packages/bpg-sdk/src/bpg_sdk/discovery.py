from __future__ import annotations

from dataclasses import dataclass
from importlib.metadata import entry_points

from bpg_sdk.authoring import Node
from bpg_sdk.manifest import NodeManifest


ENTRY_POINT_GROUP = "bpg.nodes"


class DiscoveryError(Exception):
    """Raised when installed node entry points are invalid."""


@dataclass(frozen=True)
class DiscoveredNode:
    manifest: NodeManifest
    implementation: Node


def _iter_group_entry_points() -> list:
    return list(entry_points(group=ENTRY_POINT_GROUP))


def _coerce_node(exported: object, entry_point_value: str) -> Node:
    """Coerce an entry-point export to a Node instance.

    Accepts either a Node instance (preferred) or a Node subclass with a
    no-argument constructor. Subclasses that require constructor arguments
    must be pre-instantiated and exported as an instance.
    """
    if isinstance(exported, Node):
        return exported
    if isinstance(exported, type) and issubclass(exported, Node):
        try:
            return exported()
        except Exception as exc:
            raise DiscoveryError(
                f"Entry point {entry_point_value!r} resolved to class "
                f"{exported.__name__!r} but instantiation failed: {exc}. "
                "Export a pre-instantiated Node instead."
            ) from exc
    raise DiscoveryError(
        f"Entry point {entry_point_value!r} must resolve to a Node instance or "
        "a Node subclass with a no-argument constructor."
    )


def discover_nodes() -> dict[tuple[str, str], DiscoveredNode]:
    """Load installed node packages from the `bpg.nodes` entry point group."""

    catalog: dict[tuple[str, str], DiscoveredNode] = {}
    for ep in _iter_group_entry_points():
        try:
            exported = ep.load()
        except Exception as exc:
            raise DiscoveryError(
                f"Failed to load entry point {ep.value!r}: {exc}"
            ) from exc
        node_impl = _coerce_node(exported, ep.value)
        manifest = node_impl.manifest
        if ep.name != manifest.node_id:
            raise DiscoveryError(
                f"Entry point {ep.value!r} declared as {ep.name!r} does not match "
                f"manifest node_id {manifest.node_id!r}."
            )
        key = (manifest.package, manifest.node_id)
        if key in catalog:
            raise DiscoveryError(
                f"Duplicate node manifest discovered for {manifest.package}:{manifest.node_id}."
            )
        catalog[key] = DiscoveredNode(manifest=manifest, implementation=node_impl)
    return catalog
