from pathlib import Path

from bpg.testing.runner import run_spec_test_suite


def test_spec_test_runner_executes_mocked_routing_case(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
metadata:
  name: sys-spec-proc
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
"""
    )
    result = run_spec_test_suite(suite_file)
    assert result["total"] == 1
    assert result["failed"] == 0
    assert result["cases"][0]["passed"] is True
