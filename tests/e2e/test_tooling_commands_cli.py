from __future__ import annotations

import json
import re
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def _extract_run_id(stdout: str) -> str:
    match = re.search(r"Run\s+([0-9a-f-]{36})\s+status=", stdout)
    assert match is not None
    return match.group(1)


def test_e2e_tooling_patch_validate_plan_apply_run_replay(tmp_path: Path) -> None:
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
metadata:
  name: tooling-proc
  version: 1.0.0
node_types:
  ntype@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  n1:
    type: ntype@v1
    config: {}
trigger: n1
edges: []
output: n1.out
""",
        encoding="utf-8",
    )
    state_dir = tmp_path / "state"

    doctor_before = runner.invoke(app, ["doctor", str(process_file), "--json"])
    assert doctor_before.exit_code == 1
    doctor_before_payload = json.loads(doctor_before.stdout)
    assert doctor_before_payload["ok"] is False
    assert doctor_before_payload["errors"][0]["error_code"] == "E_TYPES_REQUIRED"

    suggest = runner.invoke(app, ["suggest-fix", str(process_file), "--json"])
    assert suggest.exit_code == 0
    suggest_payload = json.loads(suggest.stdout)
    patch_ops = suggest_payload["suggestions"][0]["patch"]
    patch_file = tmp_path / "patch.json"
    patch_file.write_text(json.dumps(patch_ops), encoding="utf-8")

    apply_patch_result = runner.invoke(
        app, ["apply-patch", str(process_file), str(patch_file)]
    )
    assert apply_patch_result.exit_code == 0

    doctor_after = runner.invoke(app, ["doctor", str(process_file), "--json"])
    assert doctor_after.exit_code == 0
    doctor_after_payload = json.loads(doctor_after.stdout)
    assert doctor_after_payload["ok"] is True

    fmt_result = runner.invoke(app, ["fmt", str(process_file), "--check"])
    assert fmt_result.exit_code == 0

    plan_result = runner.invoke(
        app,
        [
            "plan",
            str(process_file),
            "--state-dir",
            str(state_dir),
            "--json",
            "--explain",
        ],
    )
    assert plan_result.exit_code == 0
    plan_payload = json.loads(plan_result.stdout)
    assert plan_payload["process_name"] == "tooling-proc"
    assert "explain" in plan_payload
    assert "graph_summary" in plan_payload["explain"]

    apply_result = runner.invoke(
        app, ["apply", str(process_file), "--state-dir", str(state_dir), "--auto-approve"]
    )
    assert apply_result.exit_code == 0

    run_result = runner.invoke(app, ["run", "tooling-proc", "--state-dir", str(state_dir)])
    assert run_result.exit_code == 0
    run_id = _extract_run_id(run_result.stdout)

    replay_result = runner.invoke(
        app, ["replay", run_id, "--state-dir", str(state_dir), "--json"]
    )
    assert replay_result.exit_code == 0
    replay_payload = json.loads(replay_result.stdout)
    assert replay_payload["stored_status"] == "completed"
    assert replay_payload["replayed_status"] == "completed"
    assert replay_payload["event_counts"]["run_started"] >= 1
    assert replay_payload["event_counts"]["run_completed"] >= 1


def test_e2e_tooling_init_and_provider_introspection(tmp_path: Path) -> None:
    process_file = tmp_path / "intent-process.bpg.yaml"
    todos_file = tmp_path / "todos.json"

    init_result = runner.invoke(
        app,
        [
            "init",
            "--name",
            "extract-customer-ids",
            "--output",
            str(process_file),
            "--todos-out",
            str(todos_file),
        ],
    )
    assert init_result.exit_code == 0
    assert process_file.exists()
    assert todos_file.exists()
    todos_payload = json.loads(todos_file.read_text(encoding="utf-8"))
    assert "todos" in todos_payload
    assert len(todos_payload["todos"]) >= 2

    doctor_result = runner.invoke(app, ["doctor", str(process_file), "--json"])
    assert doctor_result.exit_code == 0
    doctor_payload = json.loads(doctor_result.stdout)
    assert doctor_payload["ok"] is True

    list_result = runner.invoke(app, ["providers", "list", "--json"])
    assert list_result.exit_code == 0
    list_payload = json.loads(list_result.stdout)
    provider_names = {item["name"] for item in list_payload["providers"]}
    assert "mock" in provider_names

    describe_result = runner.invoke(app, ["providers", "describe", "mock", "--json"])
    assert describe_result.exit_code == 0
    describe_payload = json.loads(describe_result.stdout)
    assert describe_payload["name"] == "mock"
    assert "input_schema" in describe_payload
    assert "output_schema" in describe_payload


def test_e2e_tooling_spec_test_runner(tmp_path: Path) -> None:
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
metadata:
  name: spec-test-e2e
  version: 1.0.0
types:
  TriggerIn:
    doc: string
  ExtractOut:
    confidence: number
    customer_id: string
  ReviewOut:
    approved: bool
    customer_id: string
node_types:
  trigger@v1:
    in: object
    out: TriggerIn
    provider: mock
    version: v1
    config_schema: {}
  extract@v1:
    in: TriggerIn
    out: ExtractOut
    provider: mock
    version: v1
    config_schema: {}
  review@v1:
    in: ExtractOut
    out: ReviewOut
    provider: mock
    version: v1
    config_schema: {}
nodes:
  start:
    type: trigger@v1
    config: {}
  extract:
    type: extract@v1
    config: {}
  human_review:
    type: review@v1
    config: {}
trigger: start
edges:
  - from: start
    to: extract
    with:
      doc: trigger.in.doc
  - from: extract
    to: human_review
    with:
      confidence: extract.out.confidence
      customer_id: extract.out.customer_id
output: human_review.out
""",
        encoding="utf-8",
    )
    suite_file = tmp_path / "suite.bpg.test.yaml"
    suite_file.write_text(
        """
process_file: process.bpg.yaml
tests:
  - name: low_confidence_routes_to_review
    input:
      doc: hello
    mocks:
      extract:
        confidence: 0.3
        customer_id: c-1
      human_review:
        approved: true
        customer_id: c-1
    expect:
      path_contains: [extract, human_review]
      required_fields: [approved, customer_id]
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["test", str(suite_file), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["suite"] == str(suite_file)
    assert payload["passed"] == 1
    assert payload["failed"] == 0
