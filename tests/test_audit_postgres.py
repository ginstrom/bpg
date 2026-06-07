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
    DuplicateAuditEventError,
    PostgresAuditConfig,
    PostgresAuditEventSink,
    build_audit_record,
    compute_audit_event_hash,
    verify_audit_chain,
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
def test_postgres_audit_sink_integration():
    dsn = os.getenv("BPG_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set BPG_TEST_POSTGRES_DSN to run Postgres audit integration test")

    import psycopg

    run_id = f"run-{uuid4()}"
    sink = PostgresAuditEventSink(dsn=dsn)
    with psycopg.connect(dsn) as conn:
        conn.execute(AUDIT_SCHEMA_SQL)
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

    ignoring_sink = PostgresAuditEventSink(dsn=dsn, duplicate_strategy="ignore")
    assert ignoring_sink.insert_event(first_event) is None
