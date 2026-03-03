from __future__ import annotations

from bpg.compiler.ir import build_process_spec_ir
from bpg.compiler.normalize import normalize_process
from bpg.models.schema import Edge, NodeInstance, NodeType, Process, TypeDef


def _make_unordered_process() -> Process:
    return Process(
        metadata={"name": "norm-demo", "version": "1.0.0"},
        types={
            "ZType": TypeDef(root={"z": "string"}),
            "AType": TypeDef(root={"a": "string"}),
        },
        node_types={
            "b_node@v1": NodeType(**{"in": "AType", "out": "ZType", "provider": "mock", "version": "v1"}),
            "a_node@v1": NodeType(**{"in": "AType", "out": "AType", "provider": "mock", "version": "v1"}),
        },
        nodes={
            "z_node": NodeInstance(**{"type": "b_node@v1"}),
            "a_node": NodeInstance(**{"type": "a_node@v1"}),
        },
        edges=[
            Edge(**{"from": "z_node", "to": "a_node", "with": {"b": "z_node.out.z", "a": "z_node.out.z"}}),
            Edge(**{"from": "a_node", "to": "z_node", "with": {"x": "a_node.out.a"}}),
        ],
        trigger="a_node",
    )


def test_normalize_process_sorts_top_level_sections_and_mappings():
    process = _make_unordered_process()
    normalized = normalize_process(process)
    assert list(normalized.types.keys()) == ["AType", "ZType"]
    assert list(normalized.node_types.keys()) == ["a_node@v1", "b_node@v1"]
    assert list(normalized.nodes.keys()) == ["a_node", "z_node"]
    assert list((normalized.edges[0].mapping or {}).keys()) == ["x"]
    assert list((normalized.edges[1].mapping or {}).keys()) == ["a", "b"]


def test_build_process_spec_ir_is_deterministic_for_equivalent_processes():
    left = _make_unordered_process()
    right = normalize_process(_make_unordered_process())
    left_ir = build_process_spec_ir(left)
    right_ir = build_process_spec_ir(right)
    assert left_ir == right_ir
