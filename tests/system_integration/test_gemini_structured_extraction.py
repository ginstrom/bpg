from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bpg.cli import app
from bpg.state.store import StateStore


runner = CliRunner()


@pytest.mark.system_integration
def test_system_integration_gemini_extracts_structured_invoice_data(tmp_path: Path) -> None:
    """Live system-integration test against Gemini API.

    This test is opt-in and is skipped unless:
      - BPG_SYSTEM_INTEGRATION=1
      - GOOGLE_API_KEY is set
    """

    if os.environ.get("BPG_SYSTEM_INTEGRATION") != "1":
        pytest.skip("Set BPG_SYSTEM_INTEGRATION=1 to run system integration tests")
    if not os.environ.get("GOOGLE_API_KEY"):
        pytest.skip("GOOGLE_API_KEY is required for Gemini system integration test")

    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
metadata:
  name: gemini-structured-extraction
  version: 1.0.0

types:
  DocIn:
    text: string
  Extracted:
    invoice_id: string
    vendor: string
    total_amount: number
    currency: string

node_types:
  intake@v1:
    in: DocIn
    out: DocIn
    provider: core.passthrough
    version: v1
    config_schema: {}

  extract@v1:
    in: DocIn
    out: Extracted
    provider: ai.google
    version: v1
    config_schema:
      model: string
      system_prompt: string
      output_schema: object
      temperature: number?
      max_tokens: integer?

nodes:
  intake:
    type: intake@v1
    config: {}

  extract:
    type: extract@v1
    config:
      model: gemini-2.5-flash-lite
      temperature: 0
      max_tokens: 256
      system_prompt: |
        Extract invoice fields and return only strict JSON.
        Do not infer missing values.
      output_schema:
        type: object
        required: [invoice_id, vendor, total_amount, currency]
        properties:
          invoice_id:
            type: string
          vendor:
            type: string
          total_amount:
            type: number
          currency:
            type: string

trigger: intake
edges:
  - from: intake
    to: extract
    with:
      text: intake.out.text
output: extract.out
"""
    )

    input_file = tmp_path / "input.yaml"
    input_file.write_text(
        """
text: |
  Invoice Notice
  Invoice ID: INV-2026-0042
  Vendor: Acme Analytics LLC
  Date: 2026-02-14
  Amount Due: USD 1499.95
  Payment Terms: Net 30
"""
    )

    state_dir = tmp_path / "state"

    plan_result = runner.invoke(
        app,
        ["plan", str(process_file), "--state-dir", str(state_dir)],
    )
    assert plan_result.exit_code == 0

    apply_result = runner.invoke(
        app,
        [
            "apply",
            str(process_file),
            "--state-dir",
            str(state_dir),
            "--auto-approve",
        ],
    )
    assert apply_result.exit_code == 0

    run_result = runner.invoke(
        app,
        [
            "run",
            "gemini-structured-extraction",
            "--input",
            str(input_file),
            "--state-dir",
            str(state_dir),
        ],
    )
    assert run_result.exit_code == 0

    match = re.search(r"Run\s+([0-9a-f-]{36})\s+status=", run_result.stdout)
    assert match is not None
    run_id = match.group(1)

    store = StateStore(state_dir)
    run_record = store.load_run(run_id)
    assert run_record is not None
    assert run_record["status"] == "completed"

    output = run_record["output"]
    assert isinstance(output, dict)
    assert output["invoice_id"] == "INV-2026-0042"
    assert "acme analytics" in output["vendor"].lower()
    assert float(output["total_amount"]) == pytest.approx(1499.95, rel=0.01)
    assert output["currency"].upper() == "USD"
