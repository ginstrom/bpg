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
        ValidationError: On the first semantic error encountered.  Future
            versions may collect all errors before raising.
    """
    # TODO: implement each validation step in order
    #   _validate_type_refs(process)
    #   _validate_node_type_refs(process)
    #   _validate_edge_mappings(process)
    #   _validate_when_expressions(process)
    #   _detect_cycles(process)
    #   _validate_provider_configs(process)
    raise NotImplementedError("validate_process not yet implemented")


def _validate_type_refs(process: Process) -> None:
    """Assert all type names referenced by node types exist in the type registry."""
    # TODO: implement
    raise NotImplementedError("_validate_type_refs not yet implemented")


def _validate_node_type_refs(process: Process) -> None:
    """Assert all node instance ``type`` references resolve to declared node types."""
    # TODO: implement
    raise NotImplementedError("_validate_node_type_refs not yet implemented")


def _validate_edge_mappings(process: Process) -> None:
    """Type-check all edge ``with`` blocks against target node input schemas."""
    # TODO: implement
    raise NotImplementedError("_validate_edge_mappings not yet implemented")


def _validate_when_expressions(process: Process) -> None:
    """Parse and syntax-validate all edge ``when`` condition expressions."""
    # TODO: implement
    raise NotImplementedError("_validate_when_expressions not yet implemented")


def _detect_cycles(process: Process) -> None:
    """Run DFS cycle detection on the process execution graph."""
    # TODO: implement using DFS topological sort
    raise NotImplementedError("_detect_cycles not yet implemented")


def _validate_provider_configs(process: Process) -> None:
    """Validate node instance ``config`` values against their node type ``config_schema``."""
    # TODO: implement
    raise NotImplementedError("_validate_provider_configs not yet implemented")
