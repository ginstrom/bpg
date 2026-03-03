import json
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def test_init_from_intent_writes_process_and_todos(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    todos_file = tmp_path / "todos.json"
    result = runner.invoke(
        app,
        [
            "init",
            "--from-intent",
            "review customer onboarding requests",
            "--output",
            str(process_file),
            "--todos-out",
            str(todos_file),
        ],
    )
    assert result.exit_code == 0
    assert process_file.exists()
    assert todos_file.exists()
    text = process_file.read_text()
    assert "review_step@v1" in text
    todos = json.loads(todos_file.read_text())
    assert "todos" in todos
    assert any(item["id"] == "T_HITL_POLICY" for item in todos["todos"])


def test_init_from_intent_json_output(tmp_path: Path):
    result = runner.invoke(
        app,
        [
            "init",
            "--from-intent",
            "extract customer ids",
            "--json",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert "process" in payload
    assert "todos" in payload
    assert payload["process"]["trigger"] == "input"
