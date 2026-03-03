"""BPG compiler — parses .bpg.yaml files and validates process definitions.

Compilation pipeline (§5):
    1. Parse DSL syntax from YAML
    2. Resolve and validate type references
    3. Resolve and validate node type references
    4. Type-check edge ``with`` mappings against target ``in`` schemas
    5. Validate ``when`` expressions
    6. Detect cycles in the execution graph
    7. Validate provider configs against config_schema
    8. Generate execution Intermediate Representation (IR)
    9. Diff IR against persisted state to produce a plan
"""

from bpg.compiler.ir import (
    EdgeSpecIR,
    ExecutionIR,
    FieldType,
    NodeSpecIR,
    ProcessSpecIR,
    ResolvedEdge,
    ResolvedNode,
    ResolvedTypeDef,
    TypeRefIR,
    build_process_spec_ir,
    compile_process,
    parse_field_type,
    resolve_typedef,
)
from bpg.compiler.normalize import normalize_process
from bpg.compiler.parser import ParseError, parse_process_file
from bpg.compiler.validator import ValidationError, validate_process

__all__ = [
    "ParseError",
    "ValidationError",
    "parse_process_file",
    "validate_process",
    "ExecutionIR",
    "ProcessSpecIR",
    "NodeSpecIR",
    "EdgeSpecIR",
    "TypeRefIR",
    "FieldType",
    "ResolvedEdge",
    "ResolvedNode",
    "ResolvedTypeDef",
    "compile_process",
    "build_process_spec_ir",
    "normalize_process",
    "parse_field_type",
    "resolve_typedef",
]
