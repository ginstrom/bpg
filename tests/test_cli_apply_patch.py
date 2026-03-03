from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def test_apply_patch_updates_process_file_in_place(tmp_path: Path):
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
    patch_file = tmp_path / "patch.json"
    patch_file.write_text(
        json.dumps(
            [
                {
                    "op": "add",
                    "path": "$.types",
                    "value": {"RequiredType": {"ok": "bool"}},
                }
            ]
        )
    )

    result = runner.invoke(app, ["apply-patch", str(process_file), str(patch_file)])
    assert result.exit_code == 0
    assert "Patch applied" in result.stdout
    assert "types:" in process_file.read_text()
    assert "RequiredType:" in process_file.read_text()


def test_suggest_fix_emits_patch_for_missing_types(tmp_path: Path):
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
    result = runner.invoke(app, ["suggest-fix", str(process_file), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["errors"][0]["error_code"] == "E_TYPES_REQUIRED"
    assert payload["suggestions"][0]["patch"][0]["op"] == "add"
