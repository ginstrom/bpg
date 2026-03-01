from __future__ import annotations

from pathlib import Path
import pytest
import yaml

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.planner import Plan, ImmutabilityError
from bpg.compiler.validator import validate_process
from bpg.state.store import StateStore
from bpg.runtime.engine import Engine

class BPGTestRunner:
    """Helper to simulate CLI/Lifecycle actions in E2E tests."""
    def __init__(self, workspace: Path):
        self.workspace = workspace
        self.state_dir = workspace / ".bpg-state"
        self.store = StateStore(self.state_dir)
        self.process_file = workspace / "process.bpg.yaml"

    def write_process(self, data: dict):
        self.process_file.write_text(yaml.safe_dump(data))

    def plan(self) -> Plan:
        process = parse_process_file(self.process_file)
        validate_process(process)
        new_ir = compile_process(process)
        
        process_name = process.metadata.name if process.metadata else "default"
        old_process = self.store.load_process(process_name)
        old_ir = None
        if old_process:
            old_ir = compile_process(old_process)
            
        return Plan(new_ir, old_ir)

    def apply(self) -> str:
        from bpg.compiler.ir import compile_process
        from bpg.compiler.planner import Plan
        from bpg.providers import PROVIDER_REGISTRY

        process = parse_process_file(self.process_file)
        validate_process(process)
        ir = compile_process(process)

        process_name = process.metadata.name if process.metadata else "default"
        old_process = self.store.load_process(process_name)
        old_record = self.store.load_record(process_name)
        old_deployments = (old_record or {}).get("deployments", {})
        
        old_ir = compile_process(old_process) if old_process else None
        plan = Plan(new_ir=ir, old_ir=old_ir)

        deployments: dict = dict(old_deployments)

        # Deploy added/modified nodes
        for node_name in plan.added_nodes + plan.modified_nodes:
            node_inst = process.nodes[node_name]
            node_type = process.node_types[node_inst.node_type]
            provider_cls = PROVIDER_REGISTRY.get(node_type.provider)
            if provider_cls:
                provider = provider_cls()
                artifacts = provider.deploy(node_name, dict(node_inst.config))
                deployments[node_name] = {
                    "provider_id": node_type.provider,
                    "artifacts": artifacts,
                }

        # Undeploy removed nodes
        for node_name in plan.removed_nodes:
            node_inst = old_process.nodes[node_name]
            node_type = old_process.node_types[node_inst.node_type]
            provider_cls = PROVIDER_REGISTRY.get(node_type.provider)
            if provider_cls:
                provider = provider_cls()
                old_artifacts = old_deployments.get(node_name, {}).get("artifacts", {})
                provider.undeploy(node_name, dict(node_inst.config), old_artifacts)
                deployments.pop(node_name, None)

        return self.store.save_process(ir, deployments=deployments)

    def run(self, input_payload: dict) -> str:
        process = parse_process_file(self.process_file)
        engine = Engine(process, self.store)
        return engine.trigger(input_payload)

@pytest.fixture
def runner(tmp_path: Path):
    return BPGTestRunner(tmp_path)

def test_e2e_greenfield_deployment(runner):
    # 1. Define initial process
    runner.write_process({
        "metadata": {"name": "test-process", "version": "1.0.0"},
        "types": {
            "Input": {"val": "string"},
            "Output": {"result": "string"}
        },
        "node_types": {
            "mock_node@v1": {
                "in": "Input",
                "out": "Output",
                "provider": "mock",
                "version": "v1",
                "config_schema": {"prefix": "string"}
            }
        },
        "nodes": {
            "trigger": {
                "type": "mock_node@v1",
                "config": {"prefix": "hello"}
            }
        },
        "trigger": "trigger",
        "edges": []
    })

    # 2. Plan
    plan = runner.plan()
    assert "trigger" in plan.added_nodes
    assert not plan.modified_nodes
    assert plan.trigger_changed

    # 3. Apply
    runner.apply()
    
    # 4. Verify State
    record = runner.store.load_record("test-process")
    assert record["version"] == 1
    assert record["process_version"] == "1.0.0"
    assert "trigger" in record["definition"]["nodes"]

def test_e2e_incremental_update(runner):
    # 1. Initial Apply
    runner.write_process({
        "metadata": {"name": "test-process", "version": "1.0.0"},
        "types": {"Data": {"v": "number"}},
        "node_types": {
            "mock@v1": {
                "in": "Data", "out": "Data", "provider": "mock", "version": "v1", "config_schema": {}
            }
        },
        "nodes": {"step1": {"type": "mock@v1", "config": {}}},
        "trigger": "step1",
        "edges": []
    })
    runner.apply()

    # 2. Modify process (Add a node)
    runner.write_process({
        "metadata": {"name": "test-process", "version": "1.1.0"},
        "types": {"Data": {"v": "number"}},
        "node_types": {
            "mock@v1": {
                "in": "Data", "out": "Data", "provider": "mock", "version": "v1", "config_schema": {}
            }
        },
        "nodes": {
            "step1": {"type": "mock@v1", "config": {}},
            "step2": {"type": "mock@v1", "config": {}}
        },
        "edges": [{"from": "step1", "to": "step2", "with": {"v": "step1.out.v"}}],
        "trigger": "step1"
    })

    # 3. Plan change
    plan = runner.plan()
    assert "step2" in plan.added_nodes
    assert "step1 -> step2" in plan.added_edges

    # 4. Apply
    runner.apply()
    record = runner.store.load_record("test-process")
    assert record["version"] == 2
    assert "step2" in record["definition"]["nodes"]

def test_e2e_immutability_violation(runner):
    # 1. Initial Apply
    runner.write_process({
        "metadata": {"name": "test-process", "version": "1.0.0"},
        "types": {"User": {"id": "string"}},
        "node_types": {
            "mock@v1": {"in": "User", "out": "User", "provider": "mock", "version": "v1", "config_schema": {}}
        },
        "nodes": {"n": {"type": "mock@v1", "config": {}}},
        "trigger": "n",
        "edges": []
    })
    runner.apply()

    # 2. Breaking Type Change (Violates §11.2)
    runner.write_process({
        "metadata": {"name": "test-process", "version": "1.0.0"},
        "types": {"User": {"id": "number"}}, # Changed field type
        "node_types": {
            "mock@v1": {"in": "User", "out": "User", "provider": "mock", "version": "v1", "config_schema": {}}
        },
        "nodes": {"n": {"type": "mock@v1", "config": {}}},
        "trigger": "n",
        "edges": []
    })

    with pytest.raises(ImmutabilityError, match="Type 'User' is immutable"):
        runner.plan()

def test_e2e_idempotency_and_resumption(runner):
    from bpg.providers import PROVIDER_REGISTRY
    from bpg.providers.mock import MockProvider
    from bpg.providers.base import ProviderError

    # 1. Setup Mock Provider
    mock = MockProvider()
    # Override registry for the test duration
    original_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    
    try:
        # 2. Deploy V1
        runner.write_process({
            "metadata": {"name": "test-idempotency", "version": "1.0.0"},
            "types": {"Data": {"v": "number"}},
            "node_types": {
                "mock@v1": {"in": "Data", "out": "Data", "provider": "mock", "version": "v1", "config_schema": {}}
            },
            "nodes": {
                "intake": {"type": "mock@v1", "config": {}},
                "step1": {"type": "mock@v1", "config": {}},
                "step2": {"type": "mock@v1", "config": {}}
            },
            "edges": [
                {"from": "intake", "to": "step1", "with": {"v": "intake.out.v"}},
                {"from": "step1", "to": "step2", "with": {"v": "step1.out.v"}}
            ],
            "trigger": "intake"
        })
        runner.apply()

        # 3. Configure Mock: intake and step1 succeed, step2 fails with retryable error
        mock.register_for_node("intake", {"v": 1})
        mock.register_for_node("step1", {"v": 42})
        mock.register_error("step2", ProviderError(code="transient", message="try again", retryable=True))

        # 4. Trigger Run
        run_id = runner.run({"v": 1})
        
        # Verify intake and step1 completed, step2 failed
        run_rec = runner.store.load_run(run_id)
        assert run_rec["status"] == "failed"
        node_recs = runner.store.list_node_records(run_id)
        assert node_recs["intake"]["status"] == "completed"
        assert node_recs["step1"]["status"] == "completed"
        assert node_recs["step2"]["status"] == "failed"
        
        step1_ts = node_recs["step1"]["timestamp"]
        step1_calls = len([c for c in mock.calls if c.node_name == "step1"])
        assert step1_calls == 1

        # 5. Apply V2 (Change some description, no logic change)
        runner.write_process({
            "metadata": {"name": "test-idempotency", "version": "1.1.0", "description": "v2"},
            "types": {"Data": {"v": "number"}},
            "node_types": {
                "mock@v1": {"in": "Data", "out": "Data", "provider": "mock", "version": "v1", "config_schema": {}}
            },
            "nodes": {
                "intake": {"type": "mock@v1", "config": {}},
                "step1": {"type": "mock@v1", "config": {}},
                "step2": {"type": "mock@v1", "config": {}}
            },
            "edges": [
                {"from": "intake", "to": "step1", "with": {"v": "intake.out.v"}},
                {"from": "step1", "to": "step2", "with": {"v": "step1.out.v"}}
            ],
            "trigger": "intake"
        })
        runner.apply()

        # 6. Fix Mock and Resume (Step)
        mock._errors_by_node.clear()
        mock.register_for_node("step2", {"v": 84})
        
        process = parse_process_file(runner.process_file)
        engine = Engine(process, runner.store)
        engine.step(run_id)

        # 7. Verify Idempotency
        run_rec = runner.store.load_run(run_id)
        assert run_rec["status"] == "completed"
        
        node_recs = runner.store.list_node_records(run_id)
        assert node_recs["intake"]["status"] == "completed"
        assert node_recs["step1"]["status"] == "completed"
        assert node_recs["step2"]["status"] == "completed"
        
        # step1 should NOT have been called again in the provider (idempotency)
        new_step1_calls = len([c for c in mock.calls if c.node_name == "step1"])
        assert new_step1_calls == 1
        
        # step2 should have been called now
        step2_calls = len([c for c in mock.calls if c.node_name == "step2"])
        assert step2_calls >= 1

    finally:
        PROVIDER_REGISTRY["mock"] = original_mock

def test_e2e_edge_condition_update(runner):
    # 1. Initial Apply: step1 -> step2 (always)
    runner.write_process({
        "metadata": {"name": "test-edges", "version": "1.0.0"},
        "types": {"Data": {"v": "number"}},
        "node_types": {
            "pass@v1": {"in": "Data", "out": "Data", "provider": "core.passthrough", "version": "v1", "config_schema": {}}
        },
        "nodes": {
            "step1": {"type": "pass@v1", "config": {}},
            "step2": {"type": "pass@v1", "config": {}}
        },
        "edges": [
            {"from": "step1", "to": "step2", "with": {"v": "step1.out.v"}}
        ],
        "trigger": "step1"
    })
    runner.apply()

    # 2. Run: step2 should execute
    run_id1 = runner.run({"v": 10})
    node_recs1 = runner.store.list_node_records(run_id1)
    assert node_recs1["step2"]["status"] == "completed"

    # 3. Update Apply: step1 -> step2 ONLY IF v > 50
    runner.write_process({
        "metadata": {"name": "test-edges", "version": "1.1.0"},
        "types": {"Data": {"v": "number"}},
        "node_types": {
            "pass@v1": {"in": "Data", "out": "Data", "provider": "core.passthrough", "version": "v1", "config_schema": {}}
        },
        "nodes": {
            "step1": {"type": "pass@v1", "config": {}},
            "step2": {"type": "pass@v1", "config": {}}
        },
        "edges": [
            {
                "from": "step1", 
                "to": "step2", 
                "when": "step1.out.v > 50", 
                "with": {"v": "step1.out.v"}
            }
        ],
        "trigger": "step1"
    })
    runner.apply()

    # 4. Run with v=10: step2 should be SKIPPED
    run_id2 = runner.run({"v": 10})
    node_recs2 = runner.store.list_node_records(run_id2)
    assert node_recs2["step2"]["status"] == "skipped"

    # 5. Run with v=60: step2 should be COMPLETED
    run_id3 = runner.run({"v": 60})
    node_recs3 = runner.store.list_node_records(run_id3)
    assert node_recs3["step2"]["status"] == "completed"

def test_e2e_node_teardown_on_removal(runner):
    from bpg.providers import PROVIDER_REGISTRY
    from bpg.providers.mock import MockProvider

    mock = MockProvider()
    original_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    
    try:
        # 1. Deploy with two nodes
        runner.write_process({
            "metadata": {"name": "test-teardown", "version": "1.0.0"},
            "types": {"Data": {"v": "number"}},
            "node_types": {
                "mock@v1": {"in": "Data", "out": "Data", "provider": "mock", "version": "v1", "config_schema": {"id": "number"}}
            },
            "nodes": {
                "step1": {"type": "mock@v1", "config": {"id": 1}},
                "step2": {"type": "mock@v1", "config": {"id": 2}}
            },
            "edges": [],
            "trigger": "step1"
        })
        mock.register_deploy("step2", {"remote_id": "ext-123"})
        runner.apply()
        
        assert len(mock.deploy_calls) == 2
        assert any(c["node_name"] == "step2" for c in mock.deploy_calls)
        
        # 2. Verify state has step2 artifacts
        record1 = runner.store.load_record("test-teardown")
        assert "step2" in record1["deployments"]
        assert record1["deployments"]["step2"]["artifacts"] == {"remote_id": "ext-123"}

        # 3. Remove step2 and Apply
        runner.write_process({
            "metadata": {"name": "test-teardown", "version": "1.1.0"},
            "types": {"Data": {"v": "number"}},
            "node_types": {
                "mock@v1": {"in": "Data", "out": "Data", "provider": "mock", "version": "v1", "config_schema": {"id": "number"}}
            },
            "nodes": {
                "step1": {"type": "mock@v1", "config": {"id": 1}}
            },
            "edges": [],
            "trigger": "step1"
        })
        runner.apply()

        # 4. Verify undeploy was called
        assert len(mock.undeploy_calls) == 1
        assert mock.undeploy_calls[0]["node_name"] == "step2"
        assert mock.undeploy_calls[0]["artifacts"] == {"remote_id": "ext-123"}
        assert mock.undeploy_calls[0]["config"] == {"id": 2}

        # 5. Verify step2 is gone from state
        record2 = runner.store.load_record("test-teardown")
        assert "step2" not in record2["definition"]["nodes"]
        assert "step2" not in record2["deployments"]

    finally:
        PROVIDER_REGISTRY["mock"] = original_mock
