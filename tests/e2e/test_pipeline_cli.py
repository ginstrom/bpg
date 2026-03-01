from __future__ import annotations

import re
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app
from bpg.state.store import StateStore


runner = CliRunner()


def test_e2e_cli_parse_and_sum_pipeline(tmp_path: Path) -> None:
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
metadata:
  name: parse-sum-pipeline
  version: 1.0.0

types:
  RawText:
    text: string
  ParsedNumbers:
    numbers: list<number>
  SumResult:
    sum: number
    count: number

node_types:
  intake_text@v1:
    in: RawText
    out: RawText
    provider: core.passthrough
    version: v1
    config_schema: {}
  parse_text@v1:
    in: RawText
    out: ParsedNumbers
    provider: text.parse_numbers
    version: v1
    config_schema: {}
  sum_numbers@v1:
    in: ParsedNumbers
    out: SumResult
    provider: math.sum_numbers
    version: v1
    config_schema: {}

nodes:
  intake:
    type: intake_text@v1
    config: {}
  parse:
    type: parse_text@v1
    config: {}
  sum:
    type: sum_numbers@v1
    config: {}

trigger: intake
edges:
  - from: intake
    to: parse
    with:
      text: intake.out.text
  - from: parse
    to: sum
    with:
      numbers: parse.out.numbers
output: sum.out.sum
"""
    )
    input_file = tmp_path / "input.yaml"
    input_file.write_text(
        """
text: "invoice lines: 3, 7 and 11"
"""
    )
    state_dir = tmp_path / "state"

    plan_result = runner.invoke(
        app,
        ["plan", str(process_file), "--state-dir", str(state_dir)],
    )
    assert plan_result.exit_code == 0
    assert "Plan for process: parse-sum-pipeline" in plan_result.stdout

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
    assert "Applied successfully" in apply_result.stdout

    run_result = runner.invoke(
        app,
        [
            "run",
            "parse-sum-pipeline",
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
    assert run_record["output"] == 21.0

    node_records = store.list_node_records(run_id)
    assert node_records["intake"]["output"]["text"] == "invoice lines: 3, 7 and 11"
    assert node_records["parse"]["output"]["numbers"] == [3.0, 7.0, 11.0]
    assert node_records["sum"]["output"]["sum"] == 21.0
    assert node_records["sum"]["output"]["count"] == 3

    status_result = runner.invoke(
        app,
        ["status", run_id, "--state-dir", str(state_dir)],
    )
    assert status_result.exit_code == 0
    assert "parse-sum-pipeline" in status_result.stdout
    assert "completed" in status_result.stdout
