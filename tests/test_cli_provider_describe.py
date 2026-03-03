import json

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def test_providers_list_json_includes_registered_provider_names():
    result = runner.invoke(app, ["providers", "list", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    names = {item["name"] for item in payload["providers"]}
    assert "mock" in names
    assert "http.webhook" in names


def test_providers_describe_json_returns_metadata():
    result = runner.invoke(app, ["providers", "describe", "mock", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["name"] == "mock"
    assert "input_schema" in payload
    assert "output_schema" in payload
    assert "examples" in payload


def test_providers_describe_unknown_provider_fails():
    result = runner.invoke(app, ["providers", "describe", "missing.provider"])
    assert result.exit_code == 1
    assert "Unknown provider" in result.stderr
