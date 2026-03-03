import json
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app
from bpg.state.store import StateStore


runner = CliRunner()


def test_replay_json_rebuilds_status_from_event_log(tmp_path: Path):
    state_dir = tmp_path / "state"
    store = StateStore(state_dir)
    store.create_run("run-1", "p1", {})
    store.update_run("run-1", {"status": "failed"})
    store.append_execution_event("run-1", {"event_type": "run_started"})
    store.append_execution_event("run-1", {"event_type": "node_completed", "node": "a", "status": "completed"})
    store.append_execution_event("run-1", {"event_type": "run_completed"})

    result = runner.invoke(app, ["replay", "run-1", "--state-dir", str(state_dir), "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["stored_status"] == "failed"
    assert payload["replayed_status"] == "completed"
    assert payload["event_total"] == 3
    assert payload["node_statuses"]["a"] == "completed"


def test_replay_missing_run_fails(tmp_path: Path):
    result = runner.invoke(app, ["replay", "missing-run", "--state-dir", str(tmp_path / "state")])
    assert result.exit_code == 1
    assert "not found" in result.stderr
