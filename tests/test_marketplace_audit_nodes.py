"""Behavior tests for optional marketplace audit helper nodes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bpg.audit import build_audit_record, verify_audit_chain
from bpg.runtime.events import BpgEvent
from bpg_nodes_audit import (
    _CORE_AUDIT_LIFECYCLE_EVENTS,
    attach_evidence_to_ticket,
    create_audit_case,
    export_audit_bundle,
    notify_compliance_channel,
    verify_audit_chain as verify_audit_chain_node,
    write_compliance_summary,
)


def _event(event_type: str, *, event_id: str, run_id: str = "run-audit-1", node_id: str | None = None):
    return BpgEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at="2026-06-07T00:00:00+00:00",
        run_id=run_id,
        process_name="audit-helper-process",
        process_version="v1",
        process_hash="hash-audit-1",
        engine_backend="test",
        node_id=node_id,
        node_type="audit.export_bundle" if node_id else None,
        actor_id="auditor-1",
        actor_type="human",
        trace_id="trace-audit-1",
        span_id="span-root" if event_type == "run_started" else f"span-{node_id}",
        payload={"status": "running"},
    )


def _rows_for_run(run_id: str = "run-audit-1") -> list[dict]:
    first = build_audit_record(
        _event("run_started", event_id="event-1", run_id=run_id),
        sequence_id=1,
        previous_hash=None,
    )
    second = build_audit_record(
        _event("node_completed", event_id="event-2", run_id=run_id, node_id="verify"),
        sequence_id=2,
        previous_hash=first.event_hash,
    )
    return [first.to_insert_row(), second.to_insert_row()]


class _FakeAuditSink:
    def __init__(self, rows: list[dict], *, checkpoints: list | None = None) -> None:
        self._rows = rows
        self._checkpoints = checkpoints or []
        self.emitted: list[dict] = []

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

    def emit(self, event) -> None:
        self.emitted.append(event)


@pytest.fixture
def fake_sink(monkeypatch):
    sink = _FakeAuditSink(_rows_for_run())

    def _resolve(*, dsn=None, dsn_env=None):
        return sink

    monkeypatch.setattr("bpg_nodes_audit.resolve_audit_sink", _resolve)
    return sink


def test_export_audit_bundle_returns_bundle_without_writing_file(fake_sink):
    result = export_audit_bundle({"run_id": "run-audit-1"})

    assert result["exported"] is False
    assert result["event_count"] == 2
    assert result["verification_valid"] is True
    assert result["bundle"]["run_id"] == "run-audit-1"
    assert fake_sink.emitted == []


def test_export_audit_bundle_writes_file(fake_sink, tmp_path: Path):
    output_path = tmp_path / "bundle.json"
    result = export_audit_bundle(
        {"run_id": "run-audit-1", "output_path": str(output_path)},
    )

    assert result["exported"] is True
    assert output_path.exists()
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert payload["run_id"] == "run-audit-1"
    assert fake_sink.emitted == []


def test_verify_audit_chain_node_reports_valid_chain(fake_sink):
    result = verify_audit_chain_node({"run_id": "run-audit-1"})

    assert result["valid"] is True
    assert result["event_count"] == 2
    assert fake_sink.emitted == []


def test_write_compliance_summary_renders_markdown(fake_sink):
    result = write_compliance_summary({"run_id": "run-audit-1"})

    assert result["format"] == "markdown"
    assert "Compliance Summary: run-audit-1" in result["summary"]
    assert result["verification_valid"] is True
    assert fake_sink.emitted == []


def test_notify_compliance_channel_dry_run_does_not_emit_audit_records(fake_sink):
    result = notify_compliance_channel(
        {
            "run_id": "run-audit-1",
            "channel": "#compliance",
            "channel_type": "slack",
            "dry_run": True,
        }
    )

    assert result["notified"] is False
    assert result["dry_run"] is True
    assert fake_sink.emitted == []


def test_create_audit_case_returns_case_metadata(fake_sink):
    result = create_audit_case({"run_id": "run-audit-1", "dry_run": True})

    assert result["case_id"].startswith("AUDIT-")
    assert result["run_id"] == "run-audit-1"
    assert fake_sink.emitted == []


def test_attach_evidence_to_ticket_accepts_bundle_hash(fake_sink):
    bundle = export_audit_bundle({"run_id": "run-audit-1"})["bundle"]
    result = attach_evidence_to_ticket(
        {
            "run_id": "run-audit-1",
            "case_id": "AUDIT-00001",
            "bundle": bundle,
            "dry_run": True,
        }
    )

    assert result["attached"] is False
    assert result["evidence_ref"]
    assert fake_sink.emitted == []


def test_helper_nodes_do_not_create_core_audit_lifecycle_records(fake_sink):
    bundle = export_audit_bundle({"run_id": "run-audit-1"})["bundle"]
    handlers = [
        lambda: export_audit_bundle({"run_id": "run-audit-1"}),
        lambda: verify_audit_chain_node({"run_id": "run-audit-1"}),
        lambda: write_compliance_summary({"run_id": "run-audit-1"}),
        lambda: notify_compliance_channel(
            {
                "run_id": "run-audit-1",
                "channel": "compliance@example.com",
                "channel_type": "email",
                "dry_run": True,
            }
        ),
        lambda: create_audit_case({"run_id": "run-audit-1", "dry_run": True}),
        lambda: attach_evidence_to_ticket(
            {
                "run_id": "run-audit-1",
                "case_id": "AUDIT-00001",
                "bundle": bundle,
                "dry_run": True,
            }
        ),
    ]

    for handler in handlers:
        handler()

    assert fake_sink.emitted == []
    assert _CORE_AUDIT_LIFECYCLE_EVENTS


def test_export_audit_bundle_fails_when_audit_storage_unavailable(monkeypatch):
    def _resolve(*, dsn=None, dsn_env=None):
        raise RuntimeError("Postgres audit DSN is required. Pass --dsn or set BPG_AUDIT_DATABASE_URL.")

    monkeypatch.setattr("bpg_nodes_audit.resolve_audit_sink", _resolve)

    with pytest.raises(RuntimeError, match="Postgres audit DSN is required"):
        export_audit_bundle({"run_id": "run-audit-1"})


def test_node_manifests_advertise_io_contracts():
    from bpg_sdk.marketplace import export_node_manifest, validate_artifacts

    nodes = [
        export_audit_bundle,
        verify_audit_chain_node,
        write_compliance_summary,
        notify_compliance_channel,
        create_audit_case,
        attach_evidence_to_ticket,
    ]

    artifacts = []
    for node_impl in nodes:
        manifest = node_impl.manifest
        assert manifest.package == "bpg.nodes.audit@v1"
        assert manifest.input_schema.get("type") == "object"
        assert manifest.output_schema.get("type") == "object"
        assert "run_id" in manifest.input_schema.get("properties", {})
        artifacts.append(export_node_manifest(manifest))

    assert validate_artifacts(artifacts) == []


def test_compliance_report_example_compiles() -> None:
    from pathlib import Path

    from bpg.compiler.parser import parse_process_spec_v2_file
    from bpg.compiler.spec_v2 import compile_process_spec_v2, validate_process_spec_v2
    from bpg_sdk.discovery import discover_nodes

    repo_root = Path(__file__).resolve().parents[1]
    process_file = repo_root / "examples" / "audit" / "compliance-report" / "process.v2.bpg.yaml"
    catalog = discover_nodes()
    node_catalog = {key: discovered.manifest for key, discovered in catalog.items()}
    spec = parse_process_spec_v2_file(process_file)
    validate_process_spec_v2(spec, node_catalog=node_catalog)
    compiled = compile_process_spec_v2(spec, node_catalog=node_catalog)

    package_ids = {node.package_id for node in compiled.execution_plan.nodes}
    assert "bpg.nodes.audit@v1" in package_ids
    assert "bpg.nodes.core@v1" in package_ids
