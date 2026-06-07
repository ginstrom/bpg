from __future__ import annotations

import json
from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app
from bpg.compiler.parser import ParseError, parse_process_file
from bpg.compiler.validator import validate_process


FIXTURES = Path(__file__).parent / "fixtures" / "audit_policy"
runner = CliRunner()


def test_audit_policy_fixture_parses_and_validates():
    process = parse_process_file(FIXTURES / "enabled.bpg.yaml")

    validate_process(process)

    audit = process.observability.audit
    assert audit is not None
    assert audit.enabled is True
    assert audit.failure_policy == "warn"
    assert audit.payload_retention == "redacted"
    assert audit.redacted_field_paths == ["text"]
    assert audit.tags == {
        "environment": "test",
        "data_classification": "confidential",
    }


def test_invalid_audit_policy_fixture_fails_with_clear_message():
    try:
        parse_process_file(FIXTURES / "invalid.bpg.yaml")
    except ParseError as exc:
        message = str(exc)
    else:
        raise AssertionError("invalid audit policy parsed successfully")

    assert "observability.audit.failure_policy" in message
    assert "observability.audit.payload_retention" in message


def test_doctor_accepts_audit_policy_fixture():
    result = runner.invoke(app, ["doctor", str(FIXTURES / "enabled.bpg.yaml"), "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["errors"] == []


def test_doctor_reports_invalid_audit_policy_fixture():
    result = runner.invoke(app, ["doctor", str(FIXTURES / "invalid.bpg.yaml"), "--json"])

    assert result.exit_code == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "observability.audit.failure_policy" in payload["errors"][0]["message"]
