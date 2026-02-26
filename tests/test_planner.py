from bpg.models.schema import Process, ProcessMetadata, NodeInstance, Edge, NodeType, TypeDef
from bpg.compiler.planner import Plan, ImmutabilityError
from bpg.compiler.ir import compile_process
from bpg.compiler.validator import validate_process
import pytest

def _ir(p: Process):
    proc = p
    if not proc.types:
        proc = proc.model_copy(update={"types": {"_RequiredType": TypeDef(root={"ok": "bool"})}})
    validate_process(proc)
    return compile_process(proc)

def test_plan_new_process():
    new_process = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"t1@v1": NodeType(**{"in": "object", "out": "object", "provider": "p", "version": "v1"})},
        nodes={"n1": NodeInstance(type="t1@v1")},
        edges=[],
        trigger="n1"
    )
    plan = Plan(new_ir=_ir(new_process))
    assert not plan.is_empty()
    assert plan.added_nodes == ["n1"]
    assert plan.trigger_changed is True

def test_plan_no_changes():
    p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"t1@v1": NodeType(**{"in": "object", "out": "object", "provider": "p", "version": "v1"})},
        nodes={"n1": NodeInstance(type="t1@v1"), "n2": NodeInstance(type="t1@v1")},
        edges=[Edge(**{"from": "n1", "to": "n2"})],
        trigger="n1"
    )
    plan = Plan(new_ir=_ir(p), old_ir=_ir(p))
    assert plan.is_empty()

def test_plan_modified_node():
    old_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"t1@v1": NodeType(**{"in": "object", "out": "object", "provider": "p", "version": "v1", "config_schema": {"a": "number"}})},
        nodes={"n1": NodeInstance(type="t1@v1", config={"a": 1})},
        edges=[],
        trigger="n1"
    )
    new_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"t1@v1": NodeType(**{"in": "object", "out": "object", "provider": "p", "version": "v1", "config_schema": {"a": "number"}})},
        nodes={"n1": NodeInstance(type="t1@v1", config={"a": 2})},
        edges=[],
        trigger="n1"
    )
    plan = Plan(new_ir=_ir(new_p), old_ir=_ir(old_p))
    assert not plan.is_empty()
    assert plan.modified_nodes == ["n1"]

def test_plan_added_removed_edges():
    old_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"t1@v1": NodeType(**{"in": "object", "out": "object", "provider": "p", "version": "v1"})},
        nodes={"n1": NodeInstance(type="t1@v1"), "n2": NodeInstance(type="t1@v1")},
        edges=[Edge(**{"from": "n1", "to": "n2"})],
        trigger="n1"
    )
    new_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"t1@v1": NodeType(**{"in": "object", "out": "object", "provider": "p", "version": "v1"})},
        nodes={"n1": NodeInstance(type="t1@v1"), "n2": NodeInstance(type="t1@v1")},
        edges=[Edge(**{"from": "n1", "to": "n2", "when": "x.out.a > 0"})],
        trigger="n1"
    )
    plan = Plan(new_ir=_ir(new_p), old_ir=_ir(old_p))
    assert not plan.is_empty()
    # In our simple _edge_id logic, changing 'when' counts as remove + add
    assert len(plan.added_edges) == 1
    assert len(plan.removed_edges) == 1
    assert "when: x.out.a > 0" in plan.added_edges[0]


def test_plan_type_immutability():
    """Any change to a TypeDef with the same name must raise ImmutabilityError."""
    old_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        types={"T": TypeDef(root={"a": "string"})},
        node_types={"nt@v1": NodeType(**{"in": "T", "out": "T", "provider": "p", "version": "v1"})},
        nodes={"n1": NodeInstance(type="nt@v1")},
        edges=[],
        trigger="n1"
    )
    new_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        types={"T": TypeDef(root={"a": "number"})},  # Changed!
        node_types={"nt@v1": NodeType(**{"in": "T", "out": "T", "provider": "p", "version": "v1"})},
        nodes={"n1": NodeInstance(type="nt@v1")},
        edges=[],
        trigger="n1"
    )
    with pytest.raises(ImmutabilityError, match="immutable once published"):
        Plan(new_ir=_ir(new_p), old_ir=_ir(old_p))


def test_plan_node_type_breaking_change_blocks():
    """Breaking change to NodeType without version bump must raise ImmutabilityError."""
    old_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"nt@v1": NodeType(**{
            "in": "object", "out": "object", "provider": "p", "version": "v1",
            "config_schema": {"a": "string"}
        })},
        nodes={"n1": NodeInstance(type="nt@v1", config={"a": "val1"})},
        edges=[],
        trigger="n1"
    )
    # 1. Change 'in' type
    new_p1 = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"nt@v1": NodeType(**{
            "in": "string", "out": "object", "provider": "p", "version": "v1",
            "config_schema": {"a": "string"}
        })},
        nodes={"n1": NodeInstance(type="nt@v1", config={"a": "val1"})},
        edges=[],
        trigger="n1"
    )
    with pytest.raises(ImmutabilityError, match="input type changed"):
        Plan(new_ir=_ir(new_p1), old_ir=_ir(old_p))

    # 2. Remove field from config_schema
    new_p2 = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"nt@v1": NodeType(**{
            "in": "object", "out": "object", "provider": "p", "version": "v1",
            "config_schema": {}
        })},
        nodes={"n1": NodeInstance(type="nt@v1", config={})},
        edges=[],
        trigger="n1"
    )
    with pytest.raises(ImmutabilityError, match="removed from config_schema"):
        Plan(new_ir=_ir(new_p2), old_ir=_ir(old_p))


def test_plan_node_type_non_breaking_change_allowed():
    """Non-breaking changes (like adding an optional field) are allowed without version bump."""
    old_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"nt@v1": NodeType(**{
            "in": "object", "out": "object", "provider": "p", "version": "v1",
            "config_schema": {"a": "string"}
        })},
        nodes={"n1": NodeInstance(type="nt@v1", config={"a": "val1"})},
        edges=[],
        trigger="n1"
    )
    new_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        node_types={"nt@v1": NodeType(**{
            "in": "object", "out": "object", "provider": "p", "version": "v1",
            "config_schema": {"a": "string", "b": "string?"}  # New optional field
        })},
        nodes={"n1": NodeInstance(type="nt@v1", config={"a": "val1"})},
        edges=[],
        trigger="n1"
    )
    plan = Plan(new_ir=_ir(new_p), old_ir=_ir(old_p))
    assert not plan.is_empty()
    # Actually, if we use the same NodeType key, do we detect it?
    # Yes, Plan compares node_type objects.
    assert plan.modified_nodes == ["n1"]
