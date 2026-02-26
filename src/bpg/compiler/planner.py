from __future__ import annotations

from typing import List, Optional
from bpg.compiler.ir import ExecutionIR
from bpg.models.schema import Edge
from bpg.compiler.validator import is_breaking_node_type_change


class ImmutabilityError(Exception):
    """Raised when a proposed change violates BPG immutability or versioning rules."""


class Plan:
    """Represents a diff between the proposed process and the currently deployed state.

    The plan is used by the CLI to show the user what will change before they apply.
    """

    def __init__(
        self,
        new_ir: ExecutionIR,
        old_ir: Optional[ExecutionIR] = None
    ) -> None:
        self.new_ir = new_ir
        self.old_ir = old_ir
        
        self.added_nodes: List[str] = []
        self.removed_nodes: List[str] = []
        self.modified_nodes: List[str] = []
        
        self.added_edges: List[str] = []
        self.removed_edges: List[str] = []
        
        self.trigger_changed: bool = False
        
        self._compute_diff()

    def _compute_diff(self) -> None:
        new_process = self.new_ir.process
        if not self.old_ir:
            # Everything is new
            self.added_nodes = sorted(list(new_process.nodes.keys()))
            self.added_edges = [self._edge_id(e) for e in new_process.edges]
            self.trigger_changed = True
            return

        old_process = self.old_ir.process

        # Nodes
        new_nodes = self.new_ir.resolved_nodes
        old_nodes = self.old_ir.resolved_nodes
        
        new_node_names = set(new_nodes.keys())
        old_node_names = set(old_nodes.keys())
        
        self.added_nodes = sorted(list(new_node_names - old_node_names))
        self.removed_nodes = sorted(list(old_node_names - new_node_names))
        
        common_nodes = new_node_names & old_node_names
        for name in sorted(list(common_nodes)):
            new_node = new_nodes[name]
            old_node = old_nodes[name]
            
            # Compare both instance (config, etc) and node_type (provider, etc)
            if new_node.instance != old_node.instance or new_node.node_type != old_node.node_type:
                self.modified_nodes.append(name)
                
        # Edges
        new_edges = {self._edge_id(e): e for e in new_process.edges}
        old_edges = {self._edge_id(e): e for e in old_process.edges}
        
        new_edge_ids = set(new_edges.keys())
        old_edge_ids = set(old_edges.keys())
        
        self.added_edges = sorted(list(new_edge_ids - old_edge_ids))
        self.removed_edges = sorted(list(old_edge_ids - new_edge_ids))
        
        # Trigger
        if new_process.trigger != old_process.trigger:
            self.trigger_changed = True

        # Check immutability / breaking changes (§11)
        self._validate_immutability(old_process, new_process)

    def _validate_immutability(self, old_process, new_process) -> None:
        """Enforce BPG §11 rules for types and node types."""
        # 1. Types are immutable once published
        for name, old_type in old_process.types.items():
            if name in new_process.types:
                if new_process.types[name] != old_type:
                    raise ImmutabilityError(
                        f"Type {name!r} is immutable once published. "
                        f"Breaking changes require a new versioned type name (e.g. {name}@v2)."
                    )

        # 2. Node types require version bump for breaking changes
        for name, old_nt in old_process.node_types.items():
            if name in new_process.node_types:
                new_nt = new_process.node_types[name]
                if new_nt.version == old_nt.version:
                    reason = is_breaking_node_type_change(old_nt, new_nt)
                    if reason:
                        raise ImmutabilityError(
                            f"Node type {name!r} (version {new_nt.version}) has a breaking "
                            f"change: {reason}. You must bump the version to apply this change."
                        )

    def _edge_id(self, e: Edge) -> str:
        """Unique identifier for an edge to detect additions/removals."""
        # Note: mapping and when are part of the edge identity for diffing purposes
        condition = f" [when: {e.when}]" if e.when else ""
        return f"{e.source} -> {e.target}{condition}"

    def is_empty(self) -> bool:
        """Returns True if there are no changes to apply."""
        return not (
            self.added_nodes or 
            self.removed_nodes or 
            self.modified_nodes or
            self.added_edges or 
            self.removed_edges or
            self.trigger_changed
        )
