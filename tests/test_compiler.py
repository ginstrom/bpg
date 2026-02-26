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
from bpg.compiler.parser import ParseError
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
            "worker@v1": NodeType(**{"in": "InType", "out": "OutType", "provider": "test", "version": "v1"}),
        },
        nodes={
            "trigger_node": NodeInstance(**{"type": "worker@v1"}),
            "worker_node": NodeInstance(**{"type": "worker@v1"}),
        },
        edges=[Edge(**{
            "from": "trigger_node",
            "to": "worker_node",
            "with": {"a": "trigger_node.out.result"},
        })],
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


def test_parse_process_with_imports_merges_registries(tmp_path: Path):
    shared = tmp_path / "shared.bpg.yaml"
    shared.write_text(
        """
types:
  SharedIn:
    title: string
node_types:
  shared_node@v1:
    in: SharedIn
    out: object
    provider: mock
    version: v1
    config_schema: {}
"""
    )
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
imports: [shared.bpg.yaml]
nodes:
  start:
    type: shared_node@v1
    config: {}
trigger: start
edges: []
"""
    )
    process = parse_process_file(process_file)
    validate_process(process)
    assert "SharedIn" in process.types
    assert "shared_node@v1" in process.node_types


def test_validate_requires_non_empty_types_section():
    process = Process(
        types={},
        node_types={
            "worker@v1": NodeType(
                **{"in": "object", "out": "object", "provider": "test", "version": "v1"}
            )
        },
        nodes={"start": NodeInstance(**{"type": "worker@v1"})},
        edges=[],
        trigger="start",
    )
    with pytest.raises(ValidationError, match="at least one type definition"):
        validate_process(process)


def test_parse_process_import_cycle_raises(tmp_path: Path):
    a = tmp_path / "a.bpg.yaml"
    b = tmp_path / "b.bpg.yaml"
    a.write_text("imports: [b.bpg.yaml]\nnodes: {n1: {type: t@v1, config: {}}}\ntrigger: n1\nedges: []\n")
    b.write_text("imports: [a.bpg.yaml]\n")
    with pytest.raises(ParseError, match="Import cycle"):
        parse_process_file(a)


def test_validate_config_schema_dotted_nested_paths():
    process = _make_process(
        node_types={
            "worker@v1": NodeType(
                **{
                    "in": "InType",
                    "out": "OutType",
                    "provider": "test",
                    "version": "v1",
                    "config_schema": {"http.headers.auth": "string", "retries": "number?"},
                }
            ),
        },
        nodes={
            "trigger_node": NodeInstance(**{"type": "worker@v1", "config": {"http": {"headers": {"auth": "x"}}}}),
            "worker_node": NodeInstance(**{"type": "worker@v1", "config": {"http": {"headers": {"auth": "y"}}}}),
        },
    )
    validate_process(process)


def test_parse_field_type_nested_list():
    ft = parse_field_type("list<list<string>>")
    assert ft.base == "list"
    assert ft.list_element == "list<string>"
    inner = parse_field_type(ft.list_element)
    assert inner.base == "list"
    assert inner.list_element == "string"


# ---------------------------------------------------------------------------
# Human node timeout contract
# ---------------------------------------------------------------------------


def test_human_node_requires_on_timeout_out():
    process = Process(
        types={
            "T": TypeDef(root={"title": "string"}),
            "Approval": TypeDef(root={"approved": "bool"}),
        },
        node_types={
            "start@v1": NodeType(**{"in": "T", "out": "T", "provider": "mock", "version": "v1"}),
            "approval@v1": NodeType(
                **{
                    "in": "T",
                    "out": "Approval",
                    "provider": "slack.interactive",
                    "version": "v1",
                    "config_schema": {"channel": "string", "buttons": "list<string>", "timeout": "duration"},
                }
            ),
        },
        nodes={
            "start": NodeInstance(**{"type": "start@v1", "config": {}}),
            "approval": NodeInstance(
                **{
                    "type": "approval@v1",
                    "config": {"channel": "#ops", "buttons": ["Approve", "Reject"], "timeout": "1h"},
                }
            ),
        },
        trigger="start",
        edges=[Edge(**{"from": "start", "to": "approval", "with": {"title": "trigger.in.title"}})],
    )
    with pytest.raises(ValidationError, match="requires on_timeout.out"):
        validate_process(process)


def test_human_dashboard_node_requires_timeout():
    process = Process(
        types={"T": TypeDef(root={"title": "string"})},
        node_types={
            "start@v1": NodeType(**{"in": "T", "out": "T", "provider": "mock", "version": "v1"}),
            "review@v1": NodeType(
                **{
                    "in": "T",
                    "out": "T",
                    "provider": "dashboard.form",
                    "version": "v1",
                    "config_schema": {"title": "string"},
                }
            ),
        },
        nodes={
            "start": NodeInstance(**{"type": "start@v1", "config": {}}),
            "review": NodeInstance(
                **{
                    "type": "review@v1",
                    "config": {"title": "Need input"},
                    "on_timeout": {"out": {"title": "fallback"}},
                }
            ),
        },
        trigger="start",
        edges=[Edge(**{"from": "start", "to": "review", "with": {"title": "trigger.in.title"}})],
    )
    with pytest.raises(ValidationError, match="requires config.timeout"):
        validate_process(process)


def test_human_node_timeout_output_must_match_out_type():
    process = Process(
        types={
            "T": TypeDef(root={"title": "string"}),
            "Approval": TypeDef(root={"approved": "bool", "reason": "string?"}),
        },
        node_types={
            "start@v1": NodeType(**{"in": "T", "out": "T", "provider": "mock", "version": "v1"}),
            "approval@v1": NodeType(
                **{
                    "in": "T",
                    "out": "Approval",
                    "provider": "slack.interactive",
                    "version": "v1",
                    "config_schema": {"channel": "string", "buttons": "list<string>", "timeout": "duration"},
                }
            ),
        },
        nodes={
            "start": NodeInstance(**{"type": "start@v1", "config": {}}),
            "approval": NodeInstance(
                **{
                    "type": "approval@v1",
                    "config": {"channel": "#ops", "buttons": ["Approve", "Reject"], "timeout": "1h"},
                    "on_timeout": {"out": {"reason": "no response"}},
                }
            ),
        },
        trigger="start",
        edges=[Edge(**{"from": "start", "to": "approval", "with": {"title": "trigger.in.title"}})],
    )
    with pytest.raises(ValidationError, match="missing required fields"):
        validate_process(process)

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
            "nt@v1": NodeType(**{"in": "T", "out": "T", "provider": "p", "version": "v1"}),
        },
        nodes={
            "A": NodeInstance(**{"type": "nt@v1"}),
            "B": NodeInstance(**{"type": "nt@v1"}),
            "C": NodeInstance(**{"type": "nt@v1"}),
        },
                    edges=[
                        Edge(**{"from": "A", "to": "B", "with": {"x": "A.out.x"}}),
                        Edge(**{"from": "B", "to": "C", "with": {"x": "B.out.x"}}),
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

    # intake_form uses dashboard.form@v1 which has in: BugReport
    intake = ir.resolved_nodes["intake_form"]
    assert "title" in intake.in_type.fields

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
    with pytest.raises(ValidationError, match="missing required fields"):
        validate_process(process)


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
    with pytest.raises(ValidationError, match="mapping contains extra fields"):
        validate_process(process)


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
# Trigger validation
# ---------------------------------------------------------------------------


def test_trigger_must_not_have_incoming_edges():
    process = _make_process(
        edges=[
            Edge(**{
                "from": "worker_node",
                "to": "trigger_node",
                "with": {"a": "worker_node.out.result"},
            })
        ]
    )
    with pytest.raises(ValidationError, match="must not have incoming edges"):
        validate_process(process)


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
    with pytest.raises(ValidationError, match="unknown node"):
        validate_process(process)


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
    with pytest.raises(ValidationError, match="unknown field"):
        validate_process(process)


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
                "with": {"a": "trigger_node.out.result"},
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
                "with": {"a": "trigger_node.out.result"},
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
                    "with": {"a": "trigger_node.out.result"},
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
                "with": {"a": "trigger_node.out.result"},
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
                "with": {"a": "trigger_node.out.result"},
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
                "with": {"a": "trigger_node.out.result"},
            })
        ]
    )
    with pytest.raises(ValidationError, match="invalid when expression"):
        validate_process(process)


def test_when_invalid_unexpected_char():
    process = _make_process(
        edges=[
            Edge(**{
                "from": "trigger_node",
                "to": "worker_node",
                "when": "x # y",
                "with": {"a": "trigger_node.out.result"},
            })
        ]
    )
    with pytest.raises(ValidationError, match="invalid when expression"):
        validate_process(process)


    with pytest.raises(ValidationError, match="invalid when expression"):
        validate_process(process)


# ---------------------------------------------------------------------------
# Node Type version validation
# ---------------------------------------------------------------------------


def test_node_type_version_invalid_format():
    """NodeType version must follow a basic version pattern."""
    process = _make_process(
        node_types={
            "worker@v1": NodeType(**{
                "in": "InType",
                "out": "OutType",
                "provider": "test",
                "version": "not-a-version",
            }),
        }
    )
    with pytest.raises(ValidationError, match="Invalid version"):
        validate_process(process)


def test_node_type_version_mismatch():
    """NodeType version in field must match version in key (if present)."""
    process = _make_process(
        node_types={
            "worker@v2": NodeType(**{
                "in": "InType",
                "out": "OutType",
                "provider": "test",
                "version": "v1",  # Mismatch: key says v2, field says v1
            }),
        }
    )
    with pytest.raises(ValidationError, match="does not match version field"):
        validate_process(process)


def test_node_type_version_no_key_version_ok():
    """If the key does not contain '@', no consistency check is performed beyond format."""
    process = _make_process(
        node_types={
            "worker": NodeType(**{
                "in": "InType",
                "out": "OutType",
                "provider": "test",
                "version": "v1.2.3",
            }),
        },
        nodes={
            "trigger_node": NodeInstance(**{"type": "worker"}),
            "worker_node": NodeInstance(**{"type": "worker"}),
        }
    )
    validate_process(process)  # should not raise


# ---------------------------------------------------------------------------
# Process output validation (§4.5)
# ---------------------------------------------------------------------------


def test_process_output_valid():
    """A valid process output reference should pass validation."""
    process = _make_process(output="worker_node.out.result")
    validate_process(process)


def test_process_output_invalid_node():
    """A process output referencing an unknown node must raise ValidationError."""
    process = _make_process(output="ghost.out.val")
    with pytest.raises(ValidationError, match="references unknown node 'ghost'"):
        validate_process(process)


def test_process_output_invalid_segment():
    """A process output must reference the 'out' segment."""
    process = _make_process(output="worker_node.in.a")
    with pytest.raises(ValidationError, match="must reference 'out' segment"):
        validate_process(process)


def test_process_output_invalid_field():
    """A process output referencing a nonexistent field must raise ValidationError."""
    process = _make_process(output="worker_node.out.no_such_field")
    with pytest.raises(ValidationError, match="references unknown field 'no_such_field'"):
        validate_process(process)
