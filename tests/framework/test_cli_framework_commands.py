"""Golden tests for the framework-first bpg-cli commands (step 09)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bpg_cli import app


runner = CliRunner()

_V2_SPEC = """\
schema_version: 2
process:
  name: parse-sum
  trigger: ingest
  nodes:
    ingest:
      ref:
        package: bpg.nodes.core@v1
        node: passthrough
    parse:
      ref:
        package: bpg.nodes.core@v1
        node: text.parse_numbers
    sum:
      ref:
        package: bpg.nodes.core@v1
        node: math.sum_numbers
  edges:
    - from: ingest
      to: parse
    - from: parse
      to: sum
"""

_V2_SPEC_SINGLE = """\
schema_version: 2
process:
  name: single-node
  trigger: ingest
  nodes:
    ingest:
      ref:
        package: bpg.nodes.core@v1
        node: passthrough
  edges: []
"""


# ---------------------------------------------------------------------------
# node list
# ---------------------------------------------------------------------------


def test_node_list_exits_ok() -> None:
    result = runner.invoke(app, ["node", "list"])
    assert result.exit_code == 0


def test_node_list_shows_core_package() -> None:
    result = runner.invoke(app, ["node", "list"])
    assert result.exit_code == 0
    assert "bpg.nodes.core@v1" in result.stdout


def test_node_list_json_has_nodes_key() -> None:
    result = runner.invoke(app, ["node", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "nodes" in payload
    assert isinstance(payload["nodes"], list)


def test_node_list_json_includes_core_package() -> None:
    result = runner.invoke(app, ["node", "list", "--json"])
    payload = json.loads(result.stdout)
    package_ids = {n["package_id"] for n in payload["nodes"]}
    assert "bpg.nodes.core@v1" in package_ids


def test_node_list_json_node_has_required_fields() -> None:
    result = runner.invoke(app, ["node", "list", "--json"])
    payload = json.loads(result.stdout)
    node = next(n for n in payload["nodes"] if n["package_id"] == "bpg.nodes.core@v1")
    assert "node_id" in node
    assert "capabilities" in node


# ---------------------------------------------------------------------------
# node describe
# ---------------------------------------------------------------------------


def test_node_describe_exits_ok() -> None:
    result = runner.invoke(app, ["node", "describe", "bpg.nodes.core@v1", "passthrough"])
    assert result.exit_code == 0


def test_node_describe_shows_node_id() -> None:
    result = runner.invoke(app, ["node", "describe", "bpg.nodes.core@v1", "passthrough"])
    assert "passthrough" in result.stdout


def test_node_describe_json_has_node_id() -> None:
    result = runner.invoke(app, ["node", "describe", "bpg.nodes.core@v1", "passthrough", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["node_id"] == "passthrough"
    assert payload["package_id"] == "bpg.nodes.core@v1"


def test_node_describe_json_has_schemas() -> None:
    result = runner.invoke(app, ["node", "describe", "bpg.nodes.core@v1", "passthrough", "--json"])
    payload = json.loads(result.stdout)
    assert "input_schema" in payload
    assert "output_schema" in payload


def test_node_describe_unknown_package_exits_nonzero() -> None:
    result = runner.invoke(app, ["node", "describe", "bpg.nodes.fake@v99", "nonexistent"])
    assert result.exit_code != 0


def test_node_describe_unknown_node_exits_nonzero() -> None:
    result = runner.invoke(app, ["node", "describe", "bpg.nodes.core@v1", "totally_fake_node"])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------


def test_validate_valid_v2_spec(tmp_path: Path) -> None:
    spec_file = tmp_path / "process.v2.bpg.yaml"
    spec_file.write_text(_V2_SPEC)
    result = runner.invoke(app, ["validate", str(spec_file)])
    assert result.exit_code == 0


def test_validate_reports_ok_in_output(tmp_path: Path) -> None:
    spec_file = tmp_path / "process.v2.bpg.yaml"
    spec_file.write_text(_V2_SPEC)
    result = runner.invoke(app, ["validate", str(spec_file)])
    assert "valid" in result.stdout.lower() or "ok" in result.stdout.lower()


def test_validate_invalid_spec_exits_nonzero(tmp_path: Path) -> None:
    spec_file = tmp_path / "bad.yaml"
    spec_file.write_text("schema_version: 2\nprocess: {}\n")
    result = runner.invoke(app, ["validate", str(spec_file)])
    assert result.exit_code != 0


def test_validate_missing_file_exits_nonzero(tmp_path: Path) -> None:
    result = runner.invoke(app, ["validate", str(tmp_path / "missing.yaml")])
    assert result.exit_code != 0


def test_validate_json_ok_field(tmp_path: Path) -> None:
    spec_file = tmp_path / "process.v2.bpg.yaml"
    spec_file.write_text(_V2_SPEC)
    result = runner.invoke(app, ["validate", str(spec_file), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_validate_json_error_field_on_failure(tmp_path: Path) -> None:
    spec_file = tmp_path / "bad.yaml"
    spec_file.write_text("schema_version: 2\nprocess: {}\n")
    result = runner.invoke(app, ["validate", str(spec_file), "--json"])
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "error" in payload


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------


def test_compile_valid_spec(tmp_path: Path) -> None:
    spec_file = tmp_path / "process.v2.bpg.yaml"
    spec_file.write_text(_V2_SPEC)
    result = runner.invoke(app, ["compile", str(spec_file)])
    assert result.exit_code == 0


def test_compile_shows_process_name(tmp_path: Path) -> None:
    spec_file = tmp_path / "process.v2.bpg.yaml"
    spec_file.write_text(_V2_SPEC)
    result = runner.invoke(app, ["compile", str(spec_file)])
    assert "parse-sum" in result.stdout


def test_compile_json_has_process_name(tmp_path: Path) -> None:
    spec_file = tmp_path / "process.v2.bpg.yaml"
    spec_file.write_text(_V2_SPEC_SINGLE)
    result = runner.invoke(app, ["compile", str(spec_file), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["process_name"] == "single-node"


def test_compile_json_has_nodes(tmp_path: Path) -> None:
    spec_file = tmp_path / "process.v2.bpg.yaml"
    spec_file.write_text(_V2_SPEC)
    result = runner.invoke(app, ["compile", str(spec_file), "--json"])
    payload = json.loads(result.stdout)
    assert "nodes" in payload
    assert len(payload["nodes"]) == 3


def test_compile_json_node_has_package_ref(tmp_path: Path) -> None:
    spec_file = tmp_path / "process.v2.bpg.yaml"
    spec_file.write_text(_V2_SPEC_SINGLE)
    result = runner.invoke(app, ["compile", str(spec_file), "--json"])
    payload = json.loads(result.stdout)
    node = payload["nodes"][0]
    assert "package_id" in node
    assert node["package_id"] == "bpg.nodes.core@v1"


def test_compile_invalid_spec_exits_nonzero(tmp_path: Path) -> None:
    spec_file = tmp_path / "bad.yaml"
    spec_file.write_text("schema_version: 2\nprocess: {}\n")
    result = runner.invoke(app, ["compile", str(spec_file)])
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# worker start (dry-run)
# ---------------------------------------------------------------------------


def test_worker_start_dry_run_exits_ok() -> None:
    result = runner.invoke(app, ["worker", "start", "--dry-run"])
    assert result.exit_code == 0


def test_worker_start_dry_run_shows_temporal_info() -> None:
    result = runner.invoke(app, ["worker", "start", "--dry-run"])
    assert "temporal" in result.stdout.lower()


def test_worker_start_dry_run_shows_host() -> None:
    result = runner.invoke(app, ["worker", "start", "--dry-run", "--host", "myhost"])
    assert "myhost" in result.stdout


# ---------------------------------------------------------------------------
# top-level help
# ---------------------------------------------------------------------------


def test_app_help_exits_ok() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0


def test_app_help_mentions_business_process_graph() -> None:
    result = runner.invoke(app, ["--help"])
    assert "Business Process Graph" in result.stdout
