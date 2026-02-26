from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.runtime.engine import Engine
from bpg.state.store import StateStore
from bpg.providers.mock import MockProvider
from bpg.providers import PROVIDER_REGISTRY
import pytest
from pathlib import Path

def test_pii_redaction(tmp_path):
    process_yaml = """
types:
  RequiredType:
    ok: bool
node_types:
  mock_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}

nodes:
  triage:
    type: mock_node@v1
    config: {}

trigger: triage

edges: []

policy:
  pii_redaction:
    - node: triage
      redact_fields: [email]
"""
    path = tmp_path / "process.bpg.yaml"
    path.write_text(process_yaml)
    
    process = parse_process_file(path)
    validate_process(process)
    
    store = StateStore(tmp_path / "state")
    
    # We need a custom mock provider that we can control
    mock = MockProvider()
    old_mock = PROVIDER_REGISTRY["mock"]
    PROVIDER_REGISTRY["mock"] = lambda: mock
    
    try:
        engine = Engine(process=process, state_store=store)
        
        # Trigger with PII
        run_id = engine.trigger(input_payload={"email": "ryan@example.com", "other": "public"})
        
        # Check node record in StateStore
        node_rec = store.load_node_record(run_id, "triage")
        
        # The record should be redacted
        assert node_rec["output"]["email"] == "[REDACTED]"
        assert node_rec["output"]["other"] == "public"
    finally:
        PROVIDER_REGISTRY["mock"] = old_mock
