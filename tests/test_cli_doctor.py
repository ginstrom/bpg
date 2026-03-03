import json
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def test_doctor_success_returns_ok_json(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
types:
  RequiredType:
    ok: bool
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
"""
    )
    result = runner.invoke(app, ["doctor", str(process_file), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["errors"] == []


def test_doctor_validation_error_returns_structured_json(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
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
"""
    )
    result = runner.invoke(app, ["doctor", str(process_file), "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["errors"][0]["error_code"] == "E_TYPES_REQUIRED"
    assert payload["errors"][0]["path"] == "$.types"
