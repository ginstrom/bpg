from __future__ import annotations

from pathlib import Path

import pytest

from bpg.compiler.parser import ParseError, parse_process_spec_v2_file
from bpg.compiler.spec_v2 import compile_process_spec_v2, validate_process_spec_v2
from bpg.compiler.validator import ValidationError


def test_parse_and_compile_process_spec_v2(tmp_path: Path):
    process_file = tmp_path / "process.v2.bpg.yaml"
    process_file.write_text(
        """
schema_version: 2
process:
  name: review_flow
  trigger: submit_request
  nodes:
    rollback_request:
      ref:
        package: bpg.nodes.core.compensation@v1
        node: rollback
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
    assert [edge.source for edge in compiled.execution_plan.edges] == [
        "manager_approval",
        "submit_request",
    ]
    assert [edge.target for edge in compiled.execution_plan.edges] == [
        "rollback_request",
        "manager_approval",
    ]
    manager_approval = next(
        node for node in compiled.execution_plan.nodes if node.node_id == "manager_approval"
    )
    assert manager_approval.package_id == "bpg.nodes.slack.approval@v1"
    assert manager_approval.approval.required is True
    assert manager_approval.compensation.strategy == "run_node"
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
    with pytest.raises(ValidationError, match="missing_handler"):
        validate_process_spec_v2(spec)


def test_validate_process_spec_v2_rejects_trigger_with_incoming_edge(tmp_path: Path):
    process_file = tmp_path / "invalid-trigger-edge.v2.bpg.yaml"
    process_file.write_text(
        """
schema_version: 2
process:
  name: invalid_trigger
  trigger: start
  nodes:
    start:
      ref:
        package: bpg.nodes.core.trigger@v1
        node: trigger
    review:
      ref:
        package: bpg.nodes.core.action@v1
        node: review
  edges:
    - from: review
      to: start
""",
        encoding="utf-8",
    )

    spec = parse_process_spec_v2_file(process_file)
    with pytest.raises(ValidationError, match="must not have incoming edges"):
        validate_process_spec_v2(spec)


def test_validate_process_spec_v2_rejects_cycles(tmp_path: Path):
    process_file = tmp_path / "invalid-cycle.v2.bpg.yaml"
    process_file.write_text(
        """
schema_version: 2
process:
  name: invalid_cycle
  trigger: start
  nodes:
    start:
      ref:
        package: bpg.nodes.core.trigger@v1
        node: trigger
    review:
      ref:
        package: bpg.nodes.core.action@v1
        node: review
    finish:
      ref:
        package: bpg.nodes.core.action@v1
        node: finish
  edges:
    - from: start
      to: review
    - from: review
      to: finish
    - from: finish
      to: review
""",
        encoding="utf-8",
    )

    spec = parse_process_spec_v2_file(process_file)
    with pytest.raises(ValidationError, match="Cycle detected"):
        validate_process_spec_v2(spec)
