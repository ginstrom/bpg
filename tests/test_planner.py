from bpg.models.schema import Process, ProcessMetadata, NodeInstance, Edge
from bpg.compiler.planner import Plan

def test_plan_new_process():
    new_process = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        nodes={"n1": NodeInstance(type="t1@v1")},
        edges=[],
        trigger="n1"
    )
    plan = Plan(new_process=new_process)
    assert not plan.is_empty()
    assert plan.added_nodes == ["n1"]
    assert plan.trigger_changed is True

def test_plan_no_changes():
    p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        nodes={"n1": NodeInstance(type="t1@v1")},
        edges=[Edge(**{"from": "n1", "to": "n2"})],
        trigger="n1"
    )
    # n2 must exist in nodes for valid process, but Plan only checks diff
    p2 = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        nodes={"n1": NodeInstance(type="t1@v1")},
        edges=[Edge(**{"from": "n1", "to": "n2"})],
        trigger="n1"
    )
    plan = Plan(new_process=p, old_process=p2)
    assert plan.is_empty()

def test_plan_modified_node():
    old_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        nodes={"n1": NodeInstance(type="t1@v1", config={"a": 1})},
        edges=[],
        trigger="n1"
    )
    new_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        nodes={"n1": NodeInstance(type="t1@v1", config={"a": 2})},
        edges=[],
        trigger="n1"
    )
    plan = Plan(new_process=new_p, old_process=old_p)
    assert not plan.is_empty()
    assert plan.modified_nodes == ["n1"]

def test_plan_added_removed_edges():
    old_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        nodes={"n1": NodeInstance(type="t1@v1"), "n2": NodeInstance(type="t1@v1")},
        edges=[Edge(**{"from": "n1", "to": "n2"})],
        trigger="n1"
    )
    new_p = Process(
        metadata=ProcessMetadata(name="test", version="1.0"),
        nodes={"n1": NodeInstance(type="t1@v1"), "n2": NodeInstance(type="t1@v1")},
        edges=[Edge(**{"from": "n1", "to": "n2", "when": "x > 0"})],
        trigger="n1"
    )
    plan = Plan(new_process=new_p, old_process=old_p)
    assert not plan.is_empty()
    # In our simple _edge_id logic, changing 'when' counts as remove + add
    assert len(plan.added_edges) == 1
    assert len(plan.removed_edges) == 1
    assert "when: x > 0" in plan.added_edges[0]
