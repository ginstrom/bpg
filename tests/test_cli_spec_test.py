import json
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def _write_process_and_suite(tmp_path: Path, *, bad_expectation: bool = False) -> Path:
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
metadata:
  name: spec-test-proc
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
"""
    )
    expected_path = "missing_node" if bad_expectation else "human_review"
    suite_file = tmp_path / "suite.bpg.test.yaml"
    suite_file.write_text(
        f"""
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
      path_contains: [extract, {expected_path}]
      required_fields: [approved, customer_id]
"""
    )
    return suite_file


def test_bpg_test_json_success(tmp_path: Path):
    suite_file = _write_process_and_suite(tmp_path)
    result = runner.invoke(app, ["test", str(suite_file), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["passed"] == 1
    assert payload["failed"] == 0


def test_bpg_test_fails_on_expectation_mismatch(tmp_path: Path):
    suite_file = _write_process_and_suite(tmp_path, bad_expectation=True)
    result = runner.invoke(app, ["test", str(suite_file), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["failed"] == 1
