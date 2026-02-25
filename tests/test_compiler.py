"""Comprehensive tests for the BPG compiler IR phase.

Tests cover:
  - parse_field_type for all BPG type string forms
  - resolve_typedef conversion
  - compile_process structure and topological ordering
  - Edge with-mapping type checking (extra fields, missing required, field refs)
  - When-expression syntax validation
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bpg.compiler.ir import (
    ExecutionIR,
    FieldType,
    compile_process,
    parse_field_type,
    resolve_typedef,
)
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import ValidationError, validate_process
from bpg.models.schema import Edge, NodeInstance, NodeType, Process, TypeDef


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _make_process(**kwargs) -> Process:
    """Build a minimal valid process; any key may be overridden via kwargs."""
    defaults: dict = dict(
        types={
            "InType": TypeDef(root={"a": "string", "b": "number?"}),
            "OutType": TypeDef(root={"result": "string"}),
        },
        node_types={
            "worker@v1": NodeType(**{"in": "InType", "out": "OutType", "provider": "test"}),
        },
        nodes={
            "trigger_node": NodeInstance(**{"type": "worker@v1"}),
            "worker_node": NodeInstance(**{"type": "worker@v1"}),
        },
        edges=[Edge(**{"from": "trigger_node", "to": "worker_node"})],
        trigger="trigger_node",
    )
    defaults.update(kwargs)
    return Process(**defaults)


# ---------------------------------------------------------------------------
# parse_field_type — primitives
# ---------------------------------------------------------------------------


def test_parse_field_type_primitives():
    for base in ("string", "number", "bool", "object"):
        ft = parse_field_type(base)
        assert ft.base == base
        assert ft.optional is False
        assert ft.is_required is True
        assert ft.enum_values == ()
        assert ft.list_element == ""


# ---------------------------------------------------------------------------
# parse_field_type — optional primitives
# ---------------------------------------------------------------------------


def test_parse_field_type_optional():
    for base in ("string", "number"):
        ft = parse_field_type(f"{base}?")
        assert ft.base == base
        assert ft.optional is True
        assert ft.is_required is False


# ---------------------------------------------------------------------------
# parse_field_type — enum
# ---------------------------------------------------------------------------


def test_parse_field_type_enum():
    ft = parse_field_type("enum(S1,S2,S3)")
    assert ft.base == "enum"
    assert ft.optional is False
    assert ft.enum_values == ("S1", "S2", "S3")

    ft_opt = parse_field_type("enum(low,med,high)?")
    assert ft_opt.base == "enum"
    assert ft_opt.optional is True
    assert ft_opt.enum_values == ("low", "med", "high")


# ---------------------------------------------------------------------------
# parse_field_type — list
# ---------------------------------------------------------------------------


def test_parse_field_type_list():
    ft = parse_field_type("list<string>")
    assert ft.base == "list"
    assert ft.optional is False
    assert ft.list_element == "string"

    ft_opt = parse_field_type("list<string>?")
    assert ft_opt.base == "list"
    assert ft_opt.optional is True
    assert ft_opt.list_element == "string"


# ---------------------------------------------------------------------------
# resolve_typedef
# ---------------------------------------------------------------------------


def test_resolve_typedef():
    typedef = TypeDef(root={
        "title": "string",
        "severity": "enum(S1,S2,S3)",
        "labels": "list<string>",
        "reporter_email": "string?",
    })
    resolved = resolve_typedef("BugReport", typedef)

    assert resolved.name == "BugReport"
    assert set(resolved.fields.keys()) == {"title", "severity", "labels", "reporter_email"}

    assert resolved.fields["title"] == FieldType(base="string", optional=False)
    assert resolved.fields["severity"].base == "enum"
    assert resolved.fields["severity"].enum_values == ("S1", "S2", "S3")
    assert resolved.fields["labels"].base == "list"
    assert resolved.fields["labels"].list_element == "string"
    assert resolved.fields["reporter_email"].optional is True

    assert set(resolved.required_fields()) == {"title", "severity", "labels"}
    assert resolved.optional_fields() == ["reporter_email"]


# ---------------------------------------------------------------------------
# compile_process — basic structure
# ---------------------------------------------------------------------------


def test_compile_process_basic():
    process = _make_process()
    validate_process(process)
    ir = compile_process(process)

    assert isinstance(ir, ExecutionIR)
    assert ir.trigger.name == "trigger_node"
    assert set(ir.resolved_nodes.keys()) == {"trigger_node", "worker_node"}
    assert len(ir.resolved_edges) == 1
    assert len(ir.topological_order) == 2
    assert ir.topological_order[0] == "trigger_node"


# ---------------------------------------------------------------------------
# compile_process — topological ordering
# ---------------------------------------------------------------------------


def test_compile_process_topo_order():
    """Linear graph A → B → C must produce topo order [A, B, C]."""
    process = Process(
        types={
            "T": TypeDef(root={"x": "string"}),
        },
        node_types={
            "nt@v1": NodeType(**{"in": "T", "out": "T", "provider": "p"}),
        },
        nodes={
            "A": NodeInstance(**{"type": "nt@v1"}),
            "B": NodeInstance(**{"type": "nt@v1"}),
            "C": NodeInstance(**{"type": "nt@v1"}),
        },
        edges=[
            Edge(**{"from": "A", "to": "B"}),
            Edge(**{"from": "B", "to": "C"}),
        ],
        trigger="A",
    )
    validate_process(process)
    ir = compile_process(process)

    assert ir.topological_order == ["A", "B", "C"]


# ---------------------------------------------------------------------------
# compile_process — full example (process.bpg.yaml)
# ---------------------------------------------------------------------------

_PROCESS_FILE = Path("/home/ryan/play/bpg/process.bpg.yaml")


def test_compile_process_full_example():
    process = parse_process_file(_PROCESS_FILE)
    validate_process(process)
    ir = compile_process(process)

    assert ir.trigger.name == "intake_form"
    assert len(ir.resolved_nodes) == 4
    assert len(ir.resolved_edges) == 4
    assert ir.topological_order[0] == "intake_form"

    # intake_form uses dashboard.form@v1 which has in: object → empty fields
    intake = ir.resolved_nodes["intake_form"]
    assert intake.in_type.fields == {}

    # triage uses triage_agent@v1 which has in: BugReport — structured
    triage = ir.resolved_nodes["triage"]
    assert "title" in triage.in_type.fields
    assert "severity" in triage.in_type.fields


# ---------------------------------------------------------------------------
# Edge mapping — missing required field
# ---------------------------------------------------------------------------


def test_edge_mapping_missing_required_field():
    """Omitting a required field in a with mapping must raise ValidationError."""
    # InType requires "a" (string) and has optional "b" (number?).
    # Provide only "b", omitting required "a".
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "with": {"b": "trigger_node.out.result"},  # "a" is missing
            })
        ]
    )
    validate_process(process)
    with pytest.raises(ValidationError, match="missing required fields"):
        compile_process(process)


# ---------------------------------------------------------------------------
# Edge mapping — extra field not in schema
# ---------------------------------------------------------------------------


def test_edge_mapping_extra_field():
    """Supplying a field absent from the target schema must raise ValidationError."""
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "with": {
                    "a": "trigger_node.out.result",
                    "nonexistent_field": "trigger_node.out.result",
                },
            })
        ]
    )
    validate_process(process)
    with pytest.raises(ValidationError, match="fields not in target schema"):
        compile_process(process)


# ---------------------------------------------------------------------------
# Edge mapping — optional field omitted is OK
# ---------------------------------------------------------------------------


def test_edge_mapping_optional_field_omitted_ok():
    """Omitting optional field 'b' while providing required 'a' is valid."""
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "with": {"a": "trigger_node.out.result"},  # "b" is optional
            })
        ]
    )
    validate_process(process)
    ir = compile_process(process)  # must not raise
    assert ir is not None


# ---------------------------------------------------------------------------
# Edge mapping — field ref to unknown node
# ---------------------------------------------------------------------------


def test_edge_mapping_field_ref_unknown_node():
    """A mapping value that references a nonexistent node must raise ValidationError."""
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "with": {
                    "a": "ghost_node.out.result",  # ghost_node does not exist
                },
            })
        ]
    )
    validate_process(process)
    with pytest.raises(ValidationError, match="unknown node"):
        compile_process(process)


# ---------------------------------------------------------------------------
# Edge mapping — field ref to unknown field on structured type
# ---------------------------------------------------------------------------


def test_edge_mapping_field_ref_unknown_field():
    """A mapping value that references a nonexistent field on a structured type
    must raise ValidationError."""
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "with": {
                    "a": "trigger_node.out.nonexistent_field",
                },
            })
        ]
    )
    validate_process(process)
    with pytest.raises(ValidationError, match="unknown field"):
        compile_process(process)


# ---------------------------------------------------------------------------
# When expressions — valid forms
# ---------------------------------------------------------------------------


def test_when_valid_comparison():
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "when": 'x.out.val == "high"',
            })
        ]
    )
    validate_process(process)
    ir = compile_process(process)
    assert ir is not None


def test_when_valid_boolean_ops():
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "when": 'a.out.x > 0 && b.out.y != "z"',
            })
        ]
    )
    validate_process(process)
    ir = compile_process(process)
    assert ir is not None


def test_when_valid_functions():
    for expr in ("is_null(x.out.val)", "is_present(x.out.val)"):
        process = _make_process(
            edges=[
                Edge(**{
                    "from": "trigger_node",
                    "to": "worker_node",
                    "when": expr,
                })
            ]
        )
        validate_process(process)
        ir = compile_process(process)
        assert ir is not None


def test_when_valid_not():
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "when": "!is_null(x.out.val)",
            })
        ]
    )
    validate_process(process)
    ir = compile_process(process)
    assert ir is not None


def test_when_valid_parens():
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "when": "(a.out.x == 1) || (b.out.y == 2)",
            })
        ]
    )
    validate_process(process)
    ir = compile_process(process)
    assert ir is not None


# ---------------------------------------------------------------------------
# When expressions — invalid forms
# ---------------------------------------------------------------------------


def test_when_invalid_unknown_function():
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "when": "forbidden_func(x)",
            })
        ]
    )
    validate_process(process)
    with pytest.raises(ValidationError, match="invalid when expression"):
        compile_process(process)


def test_when_invalid_unexpected_char():
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "when": "x # y",
            })
        ]
    )
    validate_process(process)
    with pytest.raises(ValidationError, match="invalid when expression"):
        compile_process(process)


def test_when_unbalanced_paren():
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "when": "(a == b",
            })
        ]
    )
    validate_process(process)
    with pytest.raises(ValidationError, match="invalid when expression"):
        compile_process(process)
