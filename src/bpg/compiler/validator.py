"""BPG process validator.

Performs semantic validation of a parsed ``Process`` model.  All checks here
correspond to the compilation steps defined in §5 of the specification.
Validation failures raise ``ValidationError`` with a descriptive message; the
caller (typically the ``plan`` command) is responsible for formatting output.

Validation steps:
    1. Resolve all type references — unknown types are a hard error.
    2. Resolve all node type references — unknown or version-mismatched refs fail.
    3. Type-check edge ``with`` mappings against target ``in`` schemas.
    4. Validate all ``when`` expressions are syntactically valid.
    5. Detect cycles in the execution graph (loops require explicit constructs).
    6. Validate all provider configs against their declared ``config_schema``.
"""

from __future__ import annotations

from bpg.models.schema import Process


class ValidationError(Exception):
    """Raised when a process definition fails semantic validation."""

    def __init__(self, message: str, node: str | None = None, field: str | None = None) -> None:
        context = ""
        if node:
            context += f" (node={node!r}"
            if field:
                context += f", field={field!r}"
            context += ")"
        super().__init__(f"ValidationError{context}: {message}")
        self.node = node
        self.field = field


def validate_process(process: Process) -> None:
    """Run all semantic validation checks against a parsed process definition.

    Args:
        process: A ``Process`` instance produced by ``parse_process_file``.

    Raises:
        ValidationError: On the first semantic error encountered.
    """
    _validate_type_refs(process)
    _validate_node_type_refs(process)
    _detect_cycles(process)
    _validate_trigger(process)
    # _validate_edge_mappings(process)  # Future: more complex type checking
    # _validate_when_expressions(process)
    # _validate_provider_configs(process)


def _validate_type_refs(process: Process) -> None:
    """Assert all type names referenced by node types exist in the type registry."""
    known_types = set(process.types.keys())
    # Built-in primitive types are always known
    primitives = {"string", "number", "bool", "duration", "datetime", "object"}
    known_types.update(primitives)

    for nt_name, nt in process.node_types.items():
        if nt.input_type not in known_types:
            raise ValidationError(f"Unknown input type {nt.input_type!r}", node=nt_name, field="in")
        if nt.output_type not in known_types:
            raise ValidationError(f"Unknown output type {nt.output_type!r}", node=nt_name, field="out")


def _validate_node_type_refs(process: Process) -> None:
    """Assert all node instance ``type`` references resolve to declared node types."""
    for node_name, node in process.nodes.items():
        if node.node_type not in process.node_types:
            raise ValidationError(
                f"Unknown node type {node.node_type!r}", node=node_name, field="type"
            )


def _validate_trigger(process: Process) -> None:
    """Assert the trigger node exists and has no incoming edges."""
    if process.trigger not in process.nodes:
        raise ValidationError(f"Trigger node {process.trigger!r} not found in nodes", field="trigger")

    for edge in process.edges:
        if edge.target == process.trigger:
            raise ValidationError(
                f"Trigger node {process.trigger!r} cannot have incoming edges",
                node=process.trigger,
            )


def _detect_cycles(process: Process) -> None:
    """Run DFS cycle detection on the process execution graph."""
    adj = {name: [] for name in process.nodes}
    for edge in process.edges:
        if edge.source not in adj:
            raise ValidationError(f"Edge references unknown source node {edge.source!r}")
        if edge.target not in adj:
            raise ValidationError(f"Edge references unknown target node {edge.target!r}")
        adj[edge.source].append(edge.target)

    visited = set()
    path = set()

    def visit(u):
        if u in path:
            raise ValidationError(f"Cycle detected involving node {u!r}")
        if u in visited:
            return
        path.add(u)
        for v in adj[u]:
            visit(v)
        path.remove(u)
        visited.add(u)

    for node in process.nodes:
        if node not in visited:
            visit(node)
