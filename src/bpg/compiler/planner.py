from __future__ import annotations

from typing import List, Optional, Set
from bpg.models.schema import Process, Edge


class Plan:
    """Represents a diff between the proposed process and the currently deployed state.

    The plan is used by the CLI to show the user what will change before they apply.
    """

    def __init__(
        self,
        new_process: Process,
        old_process: Optional[Process] = None
    ) -> None:
        self.new_process = new_process
        self.old_process = old_process
        
        self.added_nodes: List[str] = []
        self.removed_nodes: List[str] = []
        self.modified_nodes: List[str] = []
        
        self.added_edges: List[str] = []
        self.removed_edges: List[str] = []
        
        self.trigger_changed: bool = False
        
        self._compute_diff()

    def _compute_diff(self) -> None:
        if not self.old_process:
            # Everything is new
            self.added_nodes = sorted(list(self.new_process.nodes.keys()))
            self.added_edges = [self._edge_id(e) for e in self.new_process.edges]
            self.trigger_changed = True
            return

        # Nodes
        new_node_names = set(self.new_process.nodes.keys())
        old_node_names = set(self.old_process.nodes.keys())
        
        self.added_nodes = sorted(list(new_node_names - old_node_names))
        self.removed_nodes = sorted(list(old_node_names - new_node_names))
        
        common_nodes = new_node_names & old_node_names
        for name in sorted(list(common_nodes)):
            if self.new_process.nodes[name] != self.old_process.nodes[name]:
                self.modified_nodes.append(name)
                
        # Edges
        new_edges = {self._edge_id(e): e for e in self.new_process.edges}
        old_edges = {self._edge_id(e): e for e in self.old_process.edges}
        
        new_edge_ids = set(new_edges.keys())
        old_edge_ids = set(old_edges.keys())
        
        self.added_edges = sorted(list(new_edge_ids - old_edge_ids))
        self.removed_edges = sorted(list(old_edge_ids - new_edge_ids))
        
        # Trigger
        if self.new_process.trigger != self.old_process.trigger:
            self.trigger_changed = True

    def _edge_id(self, e: Edge) -> str:
        """Unique identifier for an edge to detect additions/removals."""
        # Note: mapping and when are part of the edge identity for diffing purposes
        # If we change a mapping, it's effectively a new edge in this simplified logic.
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
