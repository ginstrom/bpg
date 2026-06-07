"""Tests for the Postgres audit ledger projection.

Set ``BPG_TEST_POSTGRES_DSN`` to run the integration test, for example:

```
docker run --rm --name bpg-audit-test -e POSTGRES_PASSWORD=bpg \
  -e POSTGRES_USER=bpg -e POSTGRES_DB=bpg -p 55432:5432 postgres:16
BPG_TEST_POSTGRES_DSN=postgresql://bpg:bpg@localhost:55432/bpg \
  uv run pytest tests/test_audit_postgres.py -k integration
```
"""

from __future__ import annotations

import os
from uuid import uuid4

import pytest

from bpg.audit import (
    AUDIT_SCHEMA_SQL,
    AuditChainCheckpoint,
    AuditPolicyConfig,
    AuditSinkFailure,
    DuplicateAuditEventError,
    LocalFileCheckpointAnchorProvider,
    PostgresAuditConfig,
    PostgresAuditEventSink,
    audit_payload_for_event,
    build_audit_record,
    checkpoint_to_event,
    compute_audit_event_hash,
    redact_payload,
    sign_checkpoint,
    verify_audit_chain,
    verify_checkpoint_signature,
)
from bpg.runtime.events import BpgEvent, sha256_json
from bpg.runtime.observability import NoopEventSink, build_observability_sink


def _event(
    event_type: str = "run_started",
    *,
    event_id: str = "event-1",
    run_id: str = "run-1",
) -> BpgEvent:
    return BpgEvent(
        event_id=event_id,
        event_type=event_type,
        occurred_at="2026-06-07T00:00:00+00:00",
        run_id=run_id,
        process_name="audit-process",
        process_version="v1",
        process_hash="hash-1",
        engine_backend="test",
        node_id="triage" if event_type.startswith("node_") else None,
        node_type="agent.pipeline" if event_type.startswith("node_") else None,
        actor_id="user-1",
        actor_type="human",
        policy_id="policy-1",
        correlation_id="corr-1",
        external_ref="ext-1",
        trace_id="trace-1",
        span_id="span-1",
        payload={"status": "running", "nested": {"b": 2, "a": 1}},
    )


def test_audit_record_projection_hashes_payload_deterministically():
    event = _event()

    record = build_audit_record(event, sequence_id=1, previous_hash=None)
    same_record = build_audit_record(event, sequence_id=1, previous_hash=None)

    assert record.chain_scope == "run"
    assert record.chain_id == event.run_id
    assert record.payload_sha256 == sha256_json(event.payload)
    assert record.event_hash == same_record.event_hash
    assert record.event_hash == compute_audit_event_hash(record.to_insert_row())


def test_verify_audit_chain_passes_for_untouched_records():
    first = build_audit_record(
        _event("run_started", event_id="event-1"),
        sequence_id=1,
        previous_hash=None,
    )
    second = build_audit_record(
        _event("node_completed", event_id="event-2"),
        sequence_id=2,
        previous_hash=first.event_hash,
    )

    result = verify_audit_chain([second, first])

    assert result.ok is True
    assert result.checked == 2
    assert result.chain_scope == "run"
    assert result.chain_id == "run-1"


def test_verify_audit_chain_detects_payload_tampering():
    first = build_audit_record(
        _event("run_started", event_id="event-1"),
        sequence_id=1,
        previous_hash=None,
    )
    second = build_audit_record(
        _event("node_completed", event_id="event-2"),
        sequence_id=2,
        previous_hash=first.event_hash,
    )
    tampered = second.to_insert_row()
    tampered["payload"] = {"status": "completed"}

    result = verify_audit_chain([first, tampered])

    assert result.ok is False
    assert result.first_mismatch_sequence_id == 2
    assert result.message == "payload_sha256 mismatch"


def test_verify_audit_chain_detects_previous_hash_tampering():
    first = build_audit_record(
        _event("run_started", event_id="event-1"),
        sequence_id=1,
        previous_hash=None,
    )
    second = build_audit_record(
        _event("node_completed", event_id="event-2"),
        sequence_id=2,
        previous_hash=first.event_hash,
    )
    tampered = second.to_insert_row()
    tampered["previous_hash"] = "wrong"

    result = verify_audit_chain([first, tampered])

    assert result.ok is False
    assert result.first_mismatch_sequence_id == 2
    assert result.message == "previous_hash does not match prior event_hash"


def test_checkpoint_signature_uses_stable_material():
    checkpoint = AuditChainCheckpoint(
        checkpoint_id=None,
        created_at=None,
        scope="run:run-1",
        last_sequence_id=10,
        chain_head_hash="head-1",
    )

    signed = checkpoint.__class__(
        checkpoint_id=1,
        created_at="2026-06-07T00:00:00+00:00",
        scope=checkpoint.scope,
        last_sequence_id=checkpoint.last_sequence_id,
        chain_head_hash=checkpoint.chain_head_hash,
        signature=sign_checkpoint(checkpoint, signing_key="secret"),
    )

    assert signed.signature == sign_checkpoint(signed, signing_key="secret")
    assert verify_checkpoint_signature(signed, signing_key="secret") is True
    assert verify_checkpoint_signature(signed, signing_key="wrong") is False


def test_local_file_checkpoint_anchor_writes_checkpoint(tmp_path):
    checkpoint = AuditChainCheckpoint(
        checkpoint_id=None,
        created_at=None,
        scope="global",
        last_sequence_id=10,
        chain_head_hash="head-1",
        signature="hmac-sha256:test",
    )
    provider = LocalFileCheckpointAnchorProvider(tmp_path)

    result = provider.anchor(checkpoint)

    assert result.anchored_ref is not None
    assert result.metadata is not None
    assert result.metadata["sha256"]
    assert "head-1" in (tmp_path / result.anchored_ref.split("/")[-1]).read_text(encoding="utf-8")


def test_checkpoint_to_event_returns_canonical_audit_event():
    checkpoint = AuditChainCheckpoint(
        checkpoint_id=7,
        created_at="2026-06-07T00:00:00+00:00",
        scope="global",
        last_sequence_id=3,
        chain_head_hash="head-1",
        anchored_ref="file:///checkpoint",
        signature="hmac-sha256:test",
    )

    event = checkpoint_to_event(checkpoint)

    assert event.event_type == "audit_checkpointed"
    assert event.run_id == "__audit_checkpoint__"
    assert event.payload["checkpoint_id"] == 7
    assert event.payload["chain_head_hash"] == "head-1"


def test_verify_audit_chain_can_start_from_checkpoint():
    first = build_audit_record(
        _event("run_started", event_id="event-1"),
        sequence_id=1,
        previous_hash=None,
    )
    second = build_audit_record(
        _event("node_completed", event_id="event-2"),
        sequence_id=2,
        previous_hash=first.event_hash,
    )
    checkpoint = AuditChainCheckpoint(
        checkpoint_id=1,
        created_at="2026-06-07T00:00:00+00:00",
        scope="run:run-1",
        last_sequence_id=1,
        chain_head_hash=first.event_hash,
        anchored_ref=None,
    )

    result = verify_audit_chain([first, second], checkpoint=checkpoint)

    assert result.ok is True
    assert result.checked == 1
    assert result.checkpoint_id == 1
    assert result.message == "audit chain verified from checkpoint"
    assert result.anchor_verified is False
    assert result.anchor_message == "missing external anchor"


def test_verify_audit_chain_reports_missing_required_anchor():
    first = build_audit_record(
        _event("run_started", event_id="event-1"),
        sequence_id=1,
        previous_hash=None,
    )
    checkpoint = AuditChainCheckpoint(
        checkpoint_id=1,
        created_at="2026-06-07T00:00:00+00:00",
        scope="run:run-1",
        last_sequence_id=1,
        chain_head_hash=first.event_hash,
    )

    result = verify_audit_chain([first], checkpoint=checkpoint, require_anchor=True)

    assert result.ok is False
    assert result.message == "checkpoint anchor missing"
    assert result.anchor_message == "missing external anchor"


def test_verify_audit_chain_detects_tampering_after_checkpoint():
    first = build_audit_record(
        _event("run_started", event_id="event-1"),
        sequence_id=1,
        previous_hash=None,
    )
    second = build_audit_record(
        _event("node_completed", event_id="event-2"),
        sequence_id=2,
        previous_hash=first.event_hash,
    )
    checkpoint = AuditChainCheckpoint(
        checkpoint_id=1,
        created_at="2026-06-07T00:00:00+00:00",
        scope="run:run-1",
        last_sequence_id=1,
        chain_head_hash=first.event_hash,
        anchored_ref="file:///checkpoint",
    )
    tampered = second.to_insert_row()
    tampered["payload"] = {"status": "completed"}

    result = verify_audit_chain([first, tampered], checkpoint=checkpoint)

    assert result.ok is False
    assert result.first_mismatch_sequence_id == 2
    assert result.message == "payload_sha256 mismatch"
    assert result.checkpoint_id == 1


def test_postgres_audit_config_parses_root_and_observability_shapes():
    root = PostgresAuditConfig.from_mapping(
        {"audit": {"enabled": True, "sink": "postgres", "dsn": "postgresql://example"}}
    )
    nested = PostgresAuditConfig.from_mapping(
        {
            "observability": {
                "audit": {
                    "enabled": True,
                    "sink": "postgres",
                    "dsn": "postgresql://example",
                    "duplicate_strategy": "ignore",
                }
            }
        }
    )

    assert root.enabled is True
    assert root.dsn == "postgresql://example"
    assert nested.duplicate_strategy == "ignore"


def test_postgres_audit_config_reads_dsn_env(monkeypatch):
    monkeypatch.setenv("BPG_AUDIT_DATABASE_URL", "postgresql://from-env")

    config = PostgresAuditConfig.from_mapping(
        {
            "audit": {
                "enabled": True,
                "sink": "postgres",
                "dsn_env": "BPG_AUDIT_DATABASE_URL",
            }
        }
    )

    assert config.dsn == "postgresql://from-env"


def test_postgres_audit_config_rejects_invalid_policy_values():
    with pytest.raises(ValueError, match="audit.failure_policy"):
        PostgresAuditConfig.from_mapping({"audit": {"enabled": True, "failure_policy": "panic"}})

    with pytest.raises(ValueError, match="audit.payload_retention"):
        PostgresAuditConfig.from_mapping({"audit": {"enabled": True, "payload_retention": "rawish"}})


def test_audit_failure_policy_disabled_does_not_register_sink():
    sink = build_observability_sink(
        {
            "audit": {
                "enabled": True,
                "sink": "postgres",
                "dsn": "postgresql://example",
                "failure_policy": "disabled",
            }
        }
    )

    assert isinstance(sink, NoopEventSink)


def test_redacted_payload_retention_redacts_configured_and_sensitive_fields():
    event = _event()
    event = event.model_copy(
        update={
            "payload": {
                "status": "running",
                "secret": "s1",
                "profile": {"email": "ryan@example.com", "token": "t1"},
            }
        }
    )
    policy = AuditPolicyConfig(
        enabled=True,
        dsn="postgresql://example",
        payload_retention="redacted",
        redaction_policy_id="custom",
        redacted_field_paths=("profile.email",),
        tags={"environment": "test"},
    )

    payload = audit_payload_for_event(event, policy)

    assert payload["_audit"]["payload_retention"] == "redacted"
    assert payload["_audit"]["redaction_policy_id"] == "custom"
    assert payload["_audit"]["tags"] == {"environment": "test"}
    assert payload["event_payload"]["secret"] == "[REDACTED]"
    assert payload["event_payload"]["profile"]["email"] == "[REDACTED]"
    assert payload["event_payload"]["profile"]["token"] == "[REDACTED]"
    assert "$.profile.email" in payload["_audit"]["redacted_field_paths"]
    assert "$.secret" in payload["_audit"]["redacted_field_paths"]


def test_hash_only_payload_retention_stores_no_event_payload():
    event = _event()
    policy = AuditPolicyConfig(
        enabled=True,
        dsn="postgresql://example",
        payload_retention="hash_only",
    )

    payload = audit_payload_for_event(event, policy)

    assert payload == {
        "_audit": {
            "payload_retention": "hash_only",
            "payload_sha256": sha256_json(event.payload),
            "redaction_policy_id": "default",
            "redacted_field_paths": [],
            "tags": {},
        }
    }


def test_full_payload_retention_requires_explicit_policy():
    event = _event()
    default_policy = AuditPolicyConfig(enabled=True, dsn="postgresql://example")
    full_policy = AuditPolicyConfig(
        enabled=True,
        dsn="postgresql://example",
        payload_retention="full",
    )

    default_payload = audit_payload_for_event(event, default_policy)
    full_payload = audit_payload_for_event(event, full_policy)

    assert default_payload["_audit"]["payload_retention"] == "redacted"
    assert full_payload["_audit"]["payload_retention"] == "full"
    assert full_payload["event_payload"] == event.payload


def test_build_audit_record_applies_policy_metadata_and_payload_projection():
    event = _event().model_copy(update={"payload": {"password": "pw", "ok": True}})
    policy = AuditPolicyConfig(
        enabled=True,
        dsn="postgresql://example",
        retention="regulated",
        payload_retention="redacted",
        tags={"data_classification": "confidential"},
    )

    record = build_audit_record(
        event,
        sequence_id=1,
        previous_hash=None,
        audit_config=policy,
    )

    assert record.payload["_audit"]["retention"] == "regulated"
    assert record.payload["_audit"]["tags"] == {"data_classification": "confidential"}
    assert record.payload["event_payload"]["password"] == "[REDACTED]"
    assert record.payload_sha256 == sha256_json(record.payload)


def test_redact_payload_leaves_original_payload_unchanged():
    original = {"profile": {"email": "ryan@example.com"}}

    redacted, paths = redact_payload(original, configured_paths=["profile.email"])

    assert original["profile"]["email"] == "ryan@example.com"
    assert redacted["profile"]["email"] == "[REDACTED]"
    assert paths == {"$.profile.email"}


class _FailingAuditSink(PostgresAuditEventSink):
    def insert_event(self, event: BpgEvent):  # type: ignore[override]
        raise RuntimeError("database unavailable")


def test_warn_failure_policy_logs_without_raising(caplog):
    sink = _FailingAuditSink(dsn="postgresql://example", failure_policy="warn")

    assert sink.emit(_event()) is not None

    assert "Postgres audit event insert failed" in caplog.text


def test_fail_run_failure_policy_raises():
    sink = _FailingAuditSink(dsn="postgresql://example", failure_policy="fail_run")

    with pytest.raises(AuditSinkFailure, match="Postgres audit event insert failed"):
        sink.emit(_event())


def test_observability_builder_registers_audit_sink():
    sink = build_observability_sink(
        {"audit": {"enabled": True, "sink": "postgres", "dsn": "postgresql://example"}}
    )

    assert isinstance(sink, PostgresAuditEventSink)


def test_observability_builder_rejects_enabled_audit_without_dsn():
    with pytest.raises(ValueError, match="requires a dsn"):
        build_observability_sink({"audit": {"enabled": True, "sink": "postgres"}})


def test_observability_builder_keeps_extra_sinks_when_audit_disabled():
    extra = NoopEventSink()

    sink = build_observability_sink({"audit": {"enabled": False}}, extra_sinks=[extra])

    assert isinstance(sink, NoopEventSink)


@pytest.mark.integration
def test_postgres_audit_sink_integration(tmp_path):
    dsn = os.getenv("BPG_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set BPG_TEST_POSTGRES_DSN to run Postgres audit integration test")

    import psycopg

    run_id = f"run-{uuid4()}"
    sink = PostgresAuditEventSink(dsn=dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute(AUDIT_SCHEMA_SQL)
        conn.execute("truncate table audit_chain_checkpoints restart identity")
        conn.execute("truncate table audit_events restart identity")
        conn.commit()

    first_event = _event("run_started", event_id=f"{run_id}-1", run_id=run_id)
    second_event = _event("node_completed", event_id=f"{run_id}-2", run_id=run_id)
    first_record = sink.insert_event(first_event)
    second_record = sink.insert_event(second_event)

    assert first_record is not None
    assert second_record is not None
    assert second_record.previous_hash == first_record.event_hash
    assert sink.verify_run(run_id).ok is True

    checkpoint = sink.create_checkpoint(
        run_id=run_id,
        signing_key="checkpoint-secret",
        anchor_provider=LocalFileCheckpointAnchorProvider(tmp_path),
    )
    assert checkpoint.scope == f"run:{run_id}"
    assert checkpoint.last_sequence_id == second_record.sequence_id
    assert checkpoint.chain_head_hash == second_record.event_hash
    assert checkpoint.anchored_ref
    assert checkpoint.signature
    assert sink.verify_from_latest_checkpoint(run_id, signing_key="checkpoint-secret").ok is True
    assert sink.latest_checkpoint(scope=f"run:{run_id}") == checkpoint

    with pytest.raises(DuplicateAuditEventError):
        sink.insert_event(first_event)

    with psycopg.connect(dsn) as conn:
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(
                "update audit_events set payload = '{}'::jsonb where event_id = %s",
                (first_event.event_id,),
            )
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute("delete from audit_events where event_id = %s", (first_event.event_id,))
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(
                "update audit_chain_checkpoints set anchored_ref = null where checkpoint_id = %s",
                (checkpoint.checkpoint_id,),
            )
        conn.rollback()
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(
                "delete from audit_chain_checkpoints where checkpoint_id = %s",
                (checkpoint.checkpoint_id,),
            )

    ignoring_sink = PostgresAuditEventSink(dsn=dsn, duplicate_strategy="ignore")
    assert ignoring_sink.insert_event(first_event) is None
