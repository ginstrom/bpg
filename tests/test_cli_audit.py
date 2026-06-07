"""CLI tests for audit inspection and trace correlation commands."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from bpg.audit import AuditChainCheckpoint, AuditPolicyConfig, build_audit_record, verify_audit_chain
from bpg.cli import app
from bpg.runtime.events import canonical_json

runner = CliRunner()


def _event(event_type: str, *, event_id: str, run_id: str = "run-1", node_id: str | None = None):
    from bpg.runtime.events import BpgEvent

    return BpgEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at="2026-06-07T00:00:00+00:00",
        run_id=run_id,
        process_name="audit-process",
        process_version="v1",
        process_hash="hash-1",
        engine_backend="test",
        node_id=node_id,
        node_type="agent.pipeline" if node_id else None,
        actor_id="user-1",
        actor_type="human",
        trace_id="trace-root",
        span_id="span-root" if event_type == "run_started" else f"span-{node_id}",
        payload={"status": "running"},
    )


def _rows_for_run(run_id: str = "run-1") -> list[dict]:
    first = build_audit_record(
        _event("run_started", event_id="event-1", run_id=run_id),
        sequence_id=1,
        previous_hash=None,
    )
    second = build_audit_record(
        _event("node_completed", event_id="event-2", run_id=run_id, node_id="triage"),
        sequence_id=2,
        previous_hash=first.event_hash,
    )
    return [first.to_insert_row(), second.to_insert_row()]


class _FakeAuditSink:
    def __init__(self, rows: list[dict], *, checkpoints: list | None = None) -> None:
        self._rows = rows
        self._checkpoints = checkpoints or []

    def fetch_run_records(self, run_id: str) -> list[dict]:
        return [row for row in self._rows if row["chain_id"] == run_id]

    def fetch_checkpoints(self, *, scope: str | None = None):
        if scope is None:
            return self._checkpoints
        return [checkpoint for checkpoint in self._checkpoints if checkpoint.scope == scope]

    def verify_run(self, run_id: str, **kwargs):
        return verify_audit_chain(self.fetch_run_records(run_id), **kwargs)

    def verify_from_latest_checkpoint(self, run_id: str, **kwargs):
        return self.verify_run(run_id, **kwargs)

    def create_checkpoint(self, *, scope: str, run_id: str | None = None, **kwargs):
        checkpoint = AuditChainCheckpoint(
            checkpoint_id=1,
            created_at="2026-06-07T00:00:00+00:00",
            scope=scope,
            last_sequence_id=self._rows[-1]["sequence_id"],
            chain_head_hash=self._rows[-1]["event_hash"],
            anchored_ref=kwargs.get("anchored_ref"),
            signature="sig-test",
        )
        self._checkpoints.append(checkpoint)
        return checkpoint


@pytest.fixture
def fake_sink(monkeypatch):
    sink = _FakeAuditSink(_rows_for_run())

    def _resolve(*, dsn=None, dsn_env=None):
        return sink

    monkeypatch.setattr("bpg.audit.inspection.resolve_audit_sink", _resolve)
    return sink


def test_audit_show_json_lists_events(fake_sink):
    result = runner.invoke(app, ["audit", "show", "run-1", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["run_id"] == "run-1"
    assert payload["event_total"] == 2
    assert payload["events"][0]["event_type"] == "run_started"
    assert payload["events"][1]["node_id"] == "triage"
    assert payload["events"][0]["trace_id"] == "trace-root"


def test_audit_show_missing_run_fails(fake_sink):
    result = runner.invoke(app, ["audit", "show", "missing-run"])
    assert result.exit_code == 1
    assert "no audit records found" in result.stderr


def test_audit_verify_success(fake_sink):
    result = runner.invoke(app, ["audit", "verify", "run-1", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["checked"] == 2


def test_audit_verify_detects_tampering(fake_sink):
    rows = _rows_for_run()
    rows[1]["payload"] = {"status": "tampered"}
    fake_sink._rows = rows

    result = runner.invoke(app, ["audit", "verify", "run-1"])
    assert result.exit_code == 1
    assert "ok=False" in result.stdout
    assert "payload_sha256 mismatch" in result.stdout


def test_audit_export_includes_temporal_correlation(fake_sink, tmp_path: Path):
    temporal_event = _event(
        "node_completed",
        event_id="event-temporal",
        node_id="triage",
    ).model_copy(
        update={
            "temporal_namespace": "default",
            "temporal_workflow_id": "wf-1",
            "temporal_activity_id": "act-1",
            "input_sha256": "input-hash",
            "output_sha256": "output-hash",
        }
    )
    policy = AuditPolicyConfig(enabled=True, dsn="postgresql://example")
    record = build_audit_record(
        temporal_event,
        sequence_id=3,
        previous_hash=None,
        audit_config=policy,
    )
    fake_sink._rows.append(record.to_insert_row())

    output = tmp_path / "bundle-temporal.json"
    result = runner.invoke(app, ["audit", "export", "run-1", "--output", str(output)])
    assert result.exit_code == 0

    bundle = json.loads(output.read_text(encoding="utf-8"))
    assert bundle["temporal"] == {
        "namespace": "default",
        "workflow_id": "wf-1",
        "activity_id": "act-1",
    }
    correlation_rows = [
        row["payload"]["_correlation"]
        for row in bundle["events"]
        if row.get("payload", {}).get("_correlation")
    ]
    assert any(item.get("input_sha256") == "input-hash" for item in correlation_rows)
    assert any(item.get("output_sha256") == "output-hash" for item in correlation_rows)


def test_audit_export_writes_deterministic_bundle(fake_sink, tmp_path: Path):
    output = tmp_path / "bundle.json"
    result = runner.invoke(app, ["audit", "export", "run-1", "--output", str(output)])
    assert result.exit_code == 0
    assert output.exists()

    first = json.loads(output.read_text(encoding="utf-8"))
    second_result = runner.invoke(app, ["audit", "export", "run-1", "--output", str(tmp_path / "bundle-2.json")])
    assert second_result.exit_code == 0
    second = json.loads((tmp_path / "bundle-2.json").read_text(encoding="utf-8"))
    assert canonical_json(first) == canonical_json(second)
    assert first["bundle_version"] == 1
    assert first["process_hash"] == "hash-1"
    assert first["verification"]["ok"] is True
    assert first["trace_ids"] == ["trace-root"]


def test_audit_export_missing_run_fails(fake_sink):
    result = runner.invoke(app, ["audit", "export", "missing-run", "--output", "/tmp/missing.json"])
    assert result.exit_code == 1
    assert "no audit records found" in result.stderr


def test_trace_show_json_includes_span_correlation(fake_sink):
    result = runner.invoke(app, ["trace", "show", "run-1", "--json"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["trace_id"] == "trace-root"
    assert payload["root_span_id"] == "span-root"
    assert payload["node_span_ids"]["triage"] == "span-triage"


def test_audit_checkpoint_create_run_scope(fake_sink):
    result = runner.invoke(
        app,
        ["audit", "checkpoint", "create", "--scope", "run:run-1", "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["scope"] == "run:run-1"
    assert payload["checkpoint_id"] == 1
    assert payload["last_sequence_id"] == 2
    assert payload["chain_head_hash"]


def test_audit_checkpoint_create_global_scope(fake_sink):
    result = runner.invoke(
        app,
        ["audit", "checkpoint", "create", "--scope", "global", "--json"],
    )
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["scope"] == "global"


def test_audit_checkpoint_create_requires_dsn(monkeypatch):
    monkeypatch.delenv("BPG_AUDIT_DATABASE_URL", raising=False)

    result = runner.invoke(
        app,
        ["audit", "checkpoint", "create", "--scope", "run:run-1"],
    )
    assert result.exit_code == 1
    assert "BPG_AUDIT_DATABASE_URL" in result.stderr


def test_audit_show_requires_dsn(monkeypatch):
    monkeypatch.delenv("BPG_AUDIT_DATABASE_URL", raising=False)

    result = runner.invoke(app, ["audit", "show", "run-1"])
    assert result.exit_code == 1
    assert "BPG_AUDIT_DATABASE_URL" in result.stderr
