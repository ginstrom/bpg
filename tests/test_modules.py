from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.compiler.ir import compile_process
import pytest
from pathlib import Path

def test_module_validation(tmp_path):
    process_yaml = """
types:
  TriageResult:
    risk: enum(low,med,high)
    summary: string
  IssueResult:
    ticket_id: string

node_types:
  mock_triage@v1:
    in: object
    out: TriageResult
    provider: mock
    version: v1
    config_schema: {}
  slack_approval@v1:
    in: object
    out: object
    provider: slack.interactive
    version: v1
    config_schema:
      channel: string
      timeout: duration
  gitlab_issue_create@v1:
    in: object
    out: IssueResult
    provider: mock
    version: v1
    config_schema:
      project_id: string

modules:
  risk_routing@v1:
    version: v1
    inputs:
      triage_result: TriageResult
    nodes:
      approval:
        type: slack_approval@v1
        config:
          channel: "#ops"
          timeout: 1h
        on_timeout:
          out: {}
      gitlab:
        type: gitlab_issue_create@v1
        config:
          project_id: "p1"
    edges:
      - from: __input__
        to: approval
        when: triage_result.risk == "high"
        with:
          title: triage_result.summary
      - from: __input__
        to: gitlab
        when: triage_result.risk != "high"
        with:
          title: triage_result.summary
    outputs:
      ticket_id: gitlab.out.ticket_id

nodes:
  triage:
    type: mock_triage@v1
    config: {}
  
  router:
    type: risk_routing@v1
    config: {}

trigger: triage

edges:
  - from: triage
    to: router
    with:
      triage_result: triage.out
"""
    path = tmp_path / "process.bpg.yaml"
    path.write_text(process_yaml)
    
    process = parse_process_file(path)
    validate_process(process)
    ir = compile_process(process)
    
    # Check inlining (using the new ____ and __ separators)
    assert "router____in__" in ir.resolved_nodes
    assert "router____out__" in ir.resolved_nodes
    assert "router__approval" in ir.resolved_nodes
    assert "router__gitlab" in ir.resolved_nodes
    
    node_names = [n.name for n in ir.resolved_nodes.values()]
    assert "router____in__" in node_names
    
    entrance_edges = [e for e in ir.resolved_edges if e.target.name == "router____in__"]
    assert len(entrance_edges) == 1
    assert entrance_edges[0].source.name == "triage"
    
    internal_edges = [e for e in ir.resolved_edges if e.source.name == "router____in__"]
    assert len(internal_edges) == 2
    targets = {e.target.name for e in internal_edges}
    assert targets == {"router__approval", "router__gitlab"}

def test_module_execution(tmp_path):
    process_yaml = """
types:
  TriageResult:
    risk: enum(low,med,high)
    summary: string
  IssueResult:
    ticket_id: string

node_types:
  mock_triage@v1:
    in: object
    out: TriageResult
    provider: mock
    version: v1
    config_schema: {}
  slack_approval@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema:
      channel: string
  gitlab_issue_create@v1:
    in: object
    out: IssueResult
    provider: mock
    version: v1
    config_schema:
      project_id: string

modules:
  risk_routing@v1:
    version: v1
    inputs:
      triage_result: TriageResult
    nodes:
      approval:
        type: slack_approval@v1
        config:
          channel: "#ops"
      gitlab:
        type: gitlab_issue_create@v1
        config:
          project_id: "p1"
    edges:
      - from: __input__
        to: approval
        when: triage_result.risk == "high"
        with:
          title: triage_result.summary
      - from: __input__
        to: gitlab
        when: triage_result.risk != "high"
        with:
          title: triage_result.summary
    outputs:
      ticket_id: gitlab.out.ticket_id

nodes:
  triage:
    type: mock_triage@v1
    config: {}
  
  router:
    type: risk_routing@v1
    config: {}

trigger: triage

edges:
  - from: triage
    to: router
    with:
      triage_result: triage.out
"""
    path = tmp_path / "process.bpg.yaml"
    path.write_text(process_yaml)
    
    from bpg.state.store import StateStore
    from bpg.runtime.engine import Engine
    from bpg.providers.mock import MockProvider
    from bpg.providers import PROVIDER_REGISTRY
    
    process = parse_process_file(path)
    store = StateStore(tmp_path / "state")
    
    # Configure mock responses (using inlined names)
    mock = MockProvider()
    mock.register_for_node("router__approval", {"approved": True})
    mock.register_for_node("router__gitlab", {"ticket_id": "T-123"})
    
    # Override registry for testing
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    
    try:
        engine = Engine(process=process, state_store=store)
        run_id = engine.trigger(input_payload={"risk": "high", "summary": "Urgent bug"})
        
        run_record = store.load_run(run_id)
        print(f"\nExecution Status for {run_id}: {run_record['status']}")
        
        # Check individual node records in StateStore
        nodes_dir = tmp_path / "state" / "runs" / run_id / "nodes"
        if nodes_dir.exists():
            for node_file in sorted(nodes_dir.glob("*.yaml")):
                import yaml as _yaml
                node_rec = _yaml.safe_load(node_file.read_text())
                print(f"  {node_rec['node']}: {node_rec['status']}")
                if 'error' in node_rec: print(f"    ERROR: {node_rec['error']}")
                if 'input' in node_rec: print(f"    INPUT: {node_rec['input']}")
                if 'output' in node_rec: print(f"    OUTPUT: {node_rec['output']}")
        
        # Check that router__approval was called (since risk=high)
        calls = [c for c in mock.calls if c.node_name == "router__approval"]
        assert len(calls) == 1
        assert calls[0].input["title"] == "Urgent bug"
        
        # Check that router__gitlab was NOT called
        gitlab_calls = [c for c in mock.calls if c.node_name == "router__gitlab"]
        assert len(gitlab_calls) == 0

        # Second run: risk=low
        mock.reset() # Clear calls
        mock.register_for_node("router__approval", {"approved": True})
        mock.register_for_node("router__gitlab", {"ticket_id": "T-456"})
        
        run_id_2 = engine.trigger(input_payload={"risk": "low", "summary": "Minor thing"})
        print(f"\nExecution Status for {run_id_2}: {store.load_run(run_id_2)['status']}")
        
        # Check that router__gitlab WAS called
        gitlab_calls = [c for c in mock.calls if c.node_name == "router__gitlab"]
        assert len(gitlab_calls) == 1
        assert gitlab_calls[0].input["title"] == "Minor thing"
        
        # Check that router____out__ WAS called and produced the ticket_id
        out_rec = store.load_node_record(run_id_2, "router____out__")
        assert out_rec["status"] == "completed"
        assert out_rec["output"]["ticket_id"] == "T-456"
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock


def test_nested_modules_compile(tmp_path):
    process_yaml = """
types:
  TriageResult:
    risk: enum(low,med,high)
    summary: string
  RiskEnvelope:
    triage_result: TriageResult
  IssueResult:
    ticket_id: string

node_types:
  mock_triage@v1:
    in: object
    out: TriageResult
    provider: mock
    version: v1
    config_schema: {}
  gitlab_issue_create@v1:
    in: object
    out: IssueResult
    provider: mock
    version: v1
    config_schema:
      project_id: string

modules:
  issue_filing@v1:
    version: v1
    inputs:
      triage_result: TriageResult
    nodes:
      gitlab:
        type: gitlab_issue_create@v1
        config:
          project_id: "p1"
    edges:
      - from: __input__
        to: gitlab
        with:
          title: triage_result.summary
    outputs:
      ticket_id: gitlab.out.ticket_id

  risk_routing@v1:
    version: v1
    inputs:
      triage_result: TriageResult
    nodes:
      filing:
        type: issue_filing@v1
        config: {}
    edges:
      - from: __input__
        to: filing
        with:
          triage_result: triage_result
    outputs:
      ticket_id: filing.out.ticket_id

nodes:
  triage:
    type: mock_triage@v1
    config: {}
  router:
    type: risk_routing@v1
    config: {}

trigger: triage
edges:
  - from: triage
    to: router
    with:
      triage_result: triage.out
"""
    path = tmp_path / "process.bpg.yaml"
    path.write_text(process_yaml)
    process = parse_process_file(path)
    validate_process(process)
    ir = compile_process(process)
    assert "router__filing____in__" in ir.resolved_nodes
    assert "router__filing__gitlab" in ir.resolved_nodes
    assert "router__filing____out__" in ir.resolved_nodes
