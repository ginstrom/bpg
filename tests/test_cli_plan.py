import json
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app
import bpg.cli as cli_module
from bpg.state.store import StateStore


runner = CliRunner()


def test_plan_pretty_output_includes_ir_and_artifact_sections(tmp_path: Path):
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

    result = runner.invoke(
        app,
        [
            "plan",
            str(process_file),
            "--state-dir",
            str(tmp_path / "state"),
        ],
    )
    assert result.exit_code == 0
    assert "IR Delta" in result.stdout
    assert "Artifact Preview" in result.stdout


def test_plan_is_dry_run_and_emits_apply_guidance(tmp_path: Path):
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
    state_dir = tmp_path / "state"
    result = runner.invoke(app, ["plan", str(process_file), "--state-dir", str(state_dir)])
    assert result.exit_code == 0
    assert "Run bpg apply" in result.stdout
    assert not (state_dir / "runs").exists()


def test_plan_writes_json_artifact_and_show_json_reads_it(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
metadata:
  name: plan-show-proc
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
    config_schema: {}
nodes:
  n1:
    type: ntype@v1
    config: {}
trigger: n1
edges: []
"""
    )
    state_dir = tmp_path / "state"
    out_file = tmp_path / "plan.out"

    plan_result = runner.invoke(
        app,
        [
            "plan",
            str(process_file),
            "--state-dir",
            str(state_dir),
            "--out",
            str(out_file),
        ],
    )
    assert plan_result.exit_code == 0
    assert out_file.exists()

    artifact = json.loads(out_file.read_text())
    assert artifact["format_version"] == 1
    assert artifact["process_name"] == "plan-show-proc"
    assert artifact["has_changes"] is True

    show_result = runner.invoke(app, ["show", "--json", str(out_file)])
    assert show_result.exit_code == 0
    shown = json.loads(show_result.stdout)
    assert shown["process_name"] == "plan-show-proc"


def test_show_human_summary(tmp_path: Path):
    plan_file = tmp_path / "plan.out"
    plan_file.write_text(
        json.dumps(
            {
                "format_version": 1,
                "generated_at": "2026-03-02T00:00:00+00:00",
                "process_name": "demo",
                "has_changes": True,
                "changes": {
                    "added_nodes": ["a"],
                    "modified_nodes": [],
                    "removed_nodes": [],
                    "added_edges": [],
                    "removed_edges": [],
                },
            }
        )
    )
    result = runner.invoke(app, ["show", str(plan_file)])
    assert result.exit_code == 0
    assert "Process:" in result.stdout
    assert "demo" in result.stdout


def test_status_shows_failure_details_and_attempts(tmp_path: Path):
    state_dir = tmp_path / "state"
    store = StateStore(state_dir)
    store.create_run("run-1", "p1", {})
    store.update_run("run-1", {"status": "failed"})
    store.save_node_record(
        "run-1",
        "triage",
        {"node": "triage", "status": "failed", "attempts": 3, "error": "rate limit"},
    )

    result = runner.invoke(app, ["status", "run-1", "--state-dir", str(state_dir)])
    assert result.exit_code == 0
    assert "attempts=3" in result.stdout
    assert "error=rate limit" in result.stdout


def test_cleanup_dry_run_reports_matches_without_deleting(tmp_path: Path):
    import yaml

    state_dir = tmp_path / "state"
    store = StateStore(state_dir)
    store.create_run("run-1", "p1", {})
    run_path = state_dir / "runs" / "run-1" / "run.yaml"
    rec = yaml.safe_load(run_path.read_text())
    rec["started_at"] = "2000-01-01T00:00:00+00:00"
    run_path.write_text(yaml.safe_dump(rec, sort_keys=False))

    result = runner.invoke(
        app,
        ["cleanup", "--state-dir", str(state_dir), "--older-than", "1d", "--dry-run"],
    )
    assert result.exit_code == 0
    assert "Would prune 1 run(s)." in result.stdout
    assert store.load_run("run-1") is not None


def test_cleanup_invalid_duration_fails(tmp_path: Path):
    state_dir = tmp_path / "state"
    result = runner.invoke(
        app,
        ["cleanup", "--state-dir", str(state_dir), "--older-than", "soon"],
    )
    assert result.exit_code == 1
    assert "invalid --older-than value" in result.stderr


def test_main_invokes_typer_app(monkeypatch):
    called = {"ok": False}

    def _fake_app():
        called["ok"] = True

    monkeypatch.setattr(cli_module, "app", _fake_app)
    cli_module.main()
    assert called["ok"] is True


def test_plan_json_errors_emits_structured_diagnostic(tmp_path: Path):
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
    result = runner.invoke(
        app,
        [
            "plan",
            str(process_file),
            "--state-dir",
            str(tmp_path / "state"),
            "--json-errors",
        ],
    )
    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert "errors" in payload
    assert payload["errors"][0]["error_code"] == "E_TYPES_REQUIRED"
    assert payload["errors"][0]["path"] == "$.types"
