import json
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app
from bpg.state.store import StateStore


runner = CliRunner()


def _write_process(path: Path, *, process_name: str = "explain-proc") -> None:
    path.write_text(
        f"""
metadata:
  name: {process_name}
  version: 1.0.0
types:
  RequiredType:
    ok: bool
node_types:
  ntype@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {{}}
nodes:
  n1:
    type: ntype@v1
    config: {{}}
trigger: n1
edges: []
"""
    )


def test_plan_json_explain_includes_explain_payload(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    _write_process(process_file)
    state_dir = tmp_path / "state"
    result = runner.invoke(
        app,
        ["plan", str(process_file), "--state-dir", str(state_dir), "--json", "--explain"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["process_name"] == "explain-proc"
    assert "explain" in payload
    assert "graph_summary" in payload["explain"]
    assert "schema_diffs" in payload["explain"]
    assert "compatibility_warnings" in payload["explain"]
    assert "blast_radius" in payload["explain"]


def test_plan_explain_reports_active_run_blast_radius(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    _write_process(process_file, process_name="blast-proc")
    state_dir = tmp_path / "state"
    store = StateStore(state_dir)
    store.create_run("run-1", "blast-proc", {})

    result = runner.invoke(
        app,
        ["plan", str(process_file), "--state-dir", str(state_dir), "--json", "--explain"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    blast = payload["explain"]["blast_radius"]
    assert blast["active_runs_count"] == 1
    assert "run-1" in blast["active_run_ids"]
