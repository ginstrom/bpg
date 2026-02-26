from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app
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
