from __future__ import annotations

from pathlib import Path

import pytest

from bpg.compiler.parser import ParseError, parse_process_spec_v2_file
from bpg.compiler.spec_v2 import compile_process_spec_v2, validate_process_spec_v2


def test_parse_and_compile_process_spec_v2(tmp_path: Path):
    process_file = tmp_path / "process.v2.bpg.yaml"
    process_file.write_text(
        """
schema_version: 2
process:
  name: review_flow
  trigger: submit_request
  nodes:
    submit_request:
      ref:
        package: bpg.nodes.core.trigger@v1
        node: trigger
    manager_approval:
      ref:
        package: bpg.nodes.slack.approval@v1
        node: approval
      timeout: 2h
      retry:
        max_attempts: 3
      approval:
        required: true
        reviewers: [managers]
      observability:
        span_name: manager-approval
        emit_input: false
      compensation:
        strategy: run_node
        node: rollback_request
    rollback_request:
      ref:
        package: bpg.nodes.core.compensation@v1
        node: rollback
  edges:
    - from: submit_request
      to: manager_approval
    - from: manager_approval
      to: rollback_request
      when: manager_approval.out.approved == false
""",
        encoding="utf-8",
    )

    spec = parse_process_spec_v2_file(process_file)
    validate_process_spec_v2(spec)
    compiled = compile_process_spec_v2(spec)

    assert compiled.execution_plan.process_name == "review_flow"
    assert compiled.execution_plan.trigger == "submit_request"
    assert [node.node_id for node in compiled.execution_plan.nodes] == [
        "submit_request",
        "manager_approval",
        "rollback_request",
    ]
    assert compiled.execution_plan.nodes[1].package_id == "bpg.nodes.slack.approval@v1"
    assert compiled.execution_plan.nodes[1].approval.required is True
    assert compiled.execution_plan.nodes[1].compensation.strategy == "run_node"
    assert compiled.capability_requirements.required_packages == [
        "bpg.nodes.core.compensation@v1",
        "bpg.nodes.core.trigger@v1",
        "bpg.nodes.slack.approval@v1",
    ]
    assert compiled.capability_requirements.approval_nodes == ["manager_approval"]
    assert compiled.capability_requirements.compensation_nodes == ["manager_approval"]
    assert compiled.capability_requirements.observability_nodes == ["manager_approval"]


def test_parse_process_spec_v2_rejects_invalid_package_identifier(tmp_path: Path):
    process_file = tmp_path / "invalid.v2.bpg.yaml"
    process_file.write_text(
        """
schema_version: 2
process:
  name: invalid_pkg
  trigger: start
  nodes:
    start:
      ref:
        package: slack.approval
        node: approval
  edges: []
""",
        encoding="utf-8",
    )

    with pytest.raises(ParseError, match="Process spec v2 validation failed") as excinfo:
        parse_process_spec_v2_file(process_file)

    assert "package" in excinfo.value.diagnostic.message


def test_validate_process_spec_v2_requires_compensation_target_node(tmp_path: Path):
    process_file = tmp_path / "invalid-compensation.v2.bpg.yaml"
    process_file.write_text(
        """
schema_version: 2
process:
  name: invalid_comp
  trigger: start
  nodes:
    start:
      ref:
        package: bpg.nodes.core.trigger@v1
        node: trigger
      compensation:
        strategy: run_node
        node: missing_handler
  edges: []
""",
        encoding="utf-8",
    )

    spec = parse_process_spec_v2_file(process_file)
    with pytest.raises(ValueError, match="missing_handler"):
        validate_process_spec_v2(spec)
