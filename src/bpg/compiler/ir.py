"""BPG Execution Intermediate Representation (IR).

Performs the compile phase after structural validation:
  1. Resolves all type references into rich FieldType / ResolvedTypeDef structures.
  2. Type-checks every edge ``with`` mapping against the target node's ``in`` schema.
  3. Validates ``when`` expressions using a recursive-descent parser.
  4. Produces a topological sort (Kahn's algorithm) for execution ordering.
  5. Returns an ExecutionIR — a fully annotated, resolved process graph.

Public API
----------
parse_field_type(type_str)     Parse a BPG type string into a FieldType.
resolve_typedef(name, typedef) Convert a TypeDef into a ResolvedTypeDef.
compile_process(process)       Main entry point; requires validate_process() first.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from bpg.compiler.types import FieldType, parse_field_type
from bpg.compiler.validator import (
    ResolvedNode,
    ResolvedTypeDef,
    ValidationError,
    resolve_typedef,
    validate_modules,
    validate_graph_structure,
    ResolvedModule,
)
from bpg.models.schema import Edge, NodeInstance, NodeType, Process, TypeDef, ModuleDefinition


# ---------------------------------------------------------------------------
# IR data types
# ---------------------------------------------------------------------------


@dataclass
class ResolvedEdge:
    """Edge with references to fully resolved source/target nodes."""

    edge: Edge
    source: ResolvedNode
    target: ResolvedNode


# ---------------------------------------------------------------------------
# IR data types
# ---------------------------------------------------------------------------


@dataclass
class ResolvedEdge:
    """Edge with references to fully resolved source/target nodes."""

    edge: Edge
    source: ResolvedNode
    target: ResolvedNode


@dataclass
class ExecutionIR:
    """Fully annotated, resolved process graph ready for runtime execution."""

    process: Process
    resolved_nodes: Dict[str, ResolvedNode]
    resolved_edges: List[ResolvedEdge]
    topological_order: List[str]  # node names in valid execution order

    @property
    def trigger(self) -> ResolvedNode:
        """Return the resolved node that acts as the process entry point."""
        name = self.process.trigger
        if name in self.resolved_nodes:
            return self.resolved_nodes[name]
        # If it was inlined, return the entrance node
        return self.resolved_nodes[f"{name}____in__"]


# ---------------------------------------------------------------------------
# Internal: topological sort (Kahn's algorithm)
# ---------------------------------------------------------------------------


def _topological_sort(process: Process) -> List[str]:
    """Produce a valid execution order for process nodes using Kahn's algorithm.

    Determinism is maintained by iterating in the original declaration order of
    ``process.nodes`` when selecting the next zero-in-degree node.

    Args:
        process: The validated (acyclic) process.

    Returns:
        A list of node names in topological order.

    Raises:
        ValidationError: If a cycle is detected (should not occur after
            ``validate_process`` has been called successfully).
    """
    # Build adjacency and in-degree structures
    adj: Dict[str, List[str]] = {name: [] for name in process.nodes}
    in_degree: Dict[str, int] = {name: 0 for name in process.nodes}

    for edge in process.edges:
        adj[edge.source].append(edge.target)
        in_degree[edge.target] += 1

    # Preserve declaration order for determinism — only used as a source of
    # candidates; deque is drained with popleft (FIFO).
    node_order = list(process.nodes.keys())

    # Seed queue with zero-in-degree nodes in declaration order
    queue: deque[str] = deque(
        name for name in node_order if in_degree[name] == 0
    )
    order: List[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbour in adj[node]:
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                # Insert in declaration order relative to other newly-zero nodes
                # by appending; full declaration-order re-sort is not required
                # because Kahn's queue naturally respects dependency ordering.
                queue.append(neighbour)

    if len(order) != len(process.nodes):
        raise ValidationError("Cycle detected during topological sort")

    return order


# ---------------------------------------------------------------------------
# Public: compile_process
# ---------------------------------------------------------------------------


def compile_process(process: Process) -> ExecutionIR:
    """Compile a validated :class:`Process` into an :class:`ExecutionIR`.

    This function assumes :func:`~bpg.compiler.validator.validate_process` has
    already been called successfully.
    """
    # Step 1: Build type registry
    type_registry: Dict[str, ResolvedTypeDef] = {}
    for type_name, typedef in process.types.items():
        type_registry[type_name] = resolve_typedef(type_name, typedef)

    # Step 2: Resolve modules
    resolved_modules = validate_modules(process, type_registry)

    # Step 3: Inline nodes and edges
    # We produce a flat list of resolved nodes and edges.
    # Module instances are expanded into constituent nodes.
    final_nodes: Dict[str, ResolvedNode] = {}
    final_edges: List[ResolvedEdge] = []

    # Helper to resolve type names
    def _resolve_type(type_name: str) -> ResolvedTypeDef:
        if type_name in type_registry:
            return type_registry[type_name]
        return ResolvedTypeDef(name=type_name, fields={})

    # Resolve top-level nodes first
    top_level_resolved = validate_graph_structure(
        name="process",
        nodes=process.nodes,
        edges=process.edges,
        trigger=process.trigger,
        type_registry=type_registry,
        node_types=process.node_types,
        modules=process.modules,
        resolved_modules=resolved_modules,
        process_output=process.output,
    )

    def _inline_module(instance_name: str, module_key: str) -> None:
        rmod = resolved_modules[module_key]
        entrance_name = f"{instance_name}____in__"
        exit_name = f"{instance_name}____out__"
        final_nodes[entrance_name] = ResolvedNode(
            name=entrance_name,
            instance=NodeInstance(type="core.passthrough", config={}),
            node_type=NodeType(
                input_type=rmod.in_type.name,
                output_type=rmod.in_type.name,
                provider="core.passthrough",
                version="v1",
            ),
            in_type=rmod.in_type,
            out_type=rmod.in_type,
        )
        final_nodes[exit_name] = ResolvedNode(
            name=exit_name,
            instance=NodeInstance(type="core.passthrough", config={}),
            node_type=NodeType(
                input_type=rmod.out_type.name,
                output_type=rmod.out_type.name,
                provider="core.passthrough",
                version="v1",
            ),
            in_type=rmod.out_type,
            out_type=rmod.out_type,
        )

        internal_modules = {
            name for name, node in rmod.definition.nodes.items() if node.node_type in process.modules
        }

        for int_name, int_rnode in rmod.internal_resolved_nodes.items():
            nested_name = f"{instance_name}__{int_name}"
            if int_name in internal_modules:
                _inline_module(nested_name, int_rnode.instance.node_type)
            else:
                final_nodes[nested_name] = ResolvedNode(
                    name=nested_name,
                    instance=int_rnode.instance,
                    node_type=int_rnode.node_type,
                    in_type=int_rnode.in_type,
                    out_type=int_rnode.out_type,
                    is_module=int_rnode.is_module,
                )

        def _prefixed_node_ref(local_name: str, for_source: bool) -> str:
            if local_name == "__input__":
                return entrance_name
            prefixed = f"{instance_name}__{local_name}"
            if local_name in internal_modules:
                return f"{prefixed}____out__" if for_source else f"{prefixed}____in__"
            return prefixed

        for ie in rmod.definition.edges:
            src_name = _prefixed_node_ref(ie.source, for_source=True)
            tgt_name = _prefixed_node_ref(ie.target, for_source=False)

            new_mapping = None
            if ie.mapping:
                new_mapping = {}
                for k, v in ie.mapping.items():
                    if not isinstance(v, str) or v.startswith("trigger.in"):
                        new_mapping[k] = v
                        continue
                    if v.startswith("__input__.in"):
                        new_mapping[k] = v.replace("__input__.in", f"{entrance_name}.out")
                        continue
                    if any(v == i or v.startswith(f"{i}.") for i in rmod.definition.inputs):
                        new_mapping[k] = f"{entrance_name}.out.{v}"
                        continue
                    v_prefix = v.split(".", 1)[0]
                    if v_prefix in internal_modules:
                        new_mapping[k] = v.replace(
                            f"{v_prefix}.out",
                            f"{instance_name}__{v_prefix}____out__.out",
                            1,
                        )
                    else:
                        new_mapping[k] = f"{instance_name}__{v}"

            new_when = ie.when
            if new_when:
                internal_node_names = set(rmod.definition.nodes.keys())

                def _prefix_ref(m):
                    ref = m.group(0)
                    if ref in ("true", "false", "null"):
                        return ref
                    if ref.startswith("__input__.in"):
                        return ref.replace("__input__.in", f"{entrance_name}.out")
                    for input_name in rmod.definition.inputs:
                        if ref == input_name or ref.startswith(f"{input_name}."):
                            return f"{entrance_name}.out.{ref}"
                    for int_node in internal_node_names:
                        if ref == int_node or ref.startswith(f"{int_node}."):
                            if int_node in internal_modules:
                                return f"{instance_name}__{ref.replace(f'{int_node}.out', f'{int_node}____out__.out', 1)}"
                            return f"{instance_name}__{ref}"
                    return ref

                new_when = re.sub(r"\b[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*\b", _prefix_ref, new_when)

            final_edges.append(ResolvedEdge(
                edge=Edge(
                    source=src_name,
                    target=tgt_name,
                    when=new_when,
                    mapping=new_mapping,
                    timeout=ie.timeout,
                    on_failure=ie.on_failure,
                ),
                source=final_nodes[src_name],
                target=final_nodes[tgt_name],
            ))

        for out_name, out_ref in rmod.definition.outputs.items():
            ref_parts = out_ref.split(".")
            local_name = ref_parts[0]
            if local_name == "__input__":
                source_node = entrance_name
                source_field = out_ref.replace("__input__.in", f"{entrance_name}.out")
            else:
                source_node = (
                    f"{instance_name}__{local_name}____out__"
                    if local_name in internal_modules
                    else f"{instance_name}__{local_name}"
                )
                source_field = f"{source_node}.out.{ref_parts[2]}"
            final_edges.append(ResolvedEdge(
                edge=Edge(source=source_node, target=exit_name, mapping={out_name: source_field}),
                source=final_nodes[source_node],
                target=final_nodes[exit_name],
            ))

    for node_name, rnode in top_level_resolved.items():
        if not rnode.is_module:
            final_nodes[node_name] = rnode
        else:
            _inline_module(node_name, rnode.instance.node_type)

    # Top-level edges
    for edge in process.edges:
        src_name = edge.source
        tgt_name = edge.target
        
        # If source or target is a module, point to its entrance/exit
        if src_name in top_level_resolved and top_level_resolved[src_name].is_module:
            src_name = f"{src_name}____out__"
        if tgt_name in top_level_resolved and top_level_resolved[tgt_name].is_module:
            tgt_name = f"{tgt_name}____in__"
            
        # Rewrite mapping for module entrance
        new_mapping = edge.mapping
        if tgt_name.endswith("____in__"):
             # If we are pointing to a module entrance, we don't need to rename fields in the mapping
             # because it's already referencing the outer nodes.
             pass
        elif new_mapping:
             # If we are pointing FROM a module exit, we need to rename M.out.field to M____out__.out.field
             new_mapping = {}
             for k, v in edge.mapping.items():
                 if isinstance(v, str) and "." in v:
                     prefix = v.split(".")[0]
                     if prefix in top_level_resolved and top_level_resolved[prefix].is_module:
                          new_mapping[k] = v.replace(f"{prefix}.out", f"{prefix}____out__.out")
                     else:
                          new_mapping[k] = v
                 else:
                     new_mapping[k] = v

        final_edges.append(ResolvedEdge(
            edge=Edge(
                source=src_name,
                target=tgt_name,
                when=edge.when,
                mapping=new_mapping,
                timeout=edge.timeout,
                on_failure=edge.on_failure,
            ),
            source=final_nodes[src_name],
            target=final_nodes[tgt_name],
        ))

    # Step 4: Topological sort
    # We need a synthetic process to run _topological_sort on
    synthetic_process = Process(
        nodes={n: r.instance for n, r in final_nodes.items()},
        edges=[re.edge for re in final_edges],
        trigger=process.trigger if not top_level_resolved[process.trigger].is_module else f"{process.trigger}____in__",
    )
    topological_order = _topological_sort(synthetic_process)

    # Step 5: Return IR
    return ExecutionIR(
        process=process, # Keep original process for metadata/policy
        resolved_nodes=final_nodes,
        resolved_edges=final_edges,
        topological_order=topological_order,
    )
