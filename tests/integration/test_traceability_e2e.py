"""End-to-end traceability integration tests against live services."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

import pytest

from bpg.audit import AUDIT_SCHEMA_SQL, PostgresAuditEventSink
from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.providers.mock import MockProvider
from bpg.runtime.langgraph_runtime import LangGraphRuntime
from bpg.runtime.observability import build_runtime_event_sink

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "audit_policy"


def _require_postgres_dsn() -> str:
    dsn = os.getenv("BPG_TEST_POSTGRES_DSN")
    if not dsn:
        pytest.skip("set BPG_TEST_POSTGRES_DSN to run traceability integration tests")
    return dsn


def _reset_audit_schema(dsn: str) -> None:
    import psycopg

    with psycopg.connect(dsn) as conn:
        conn.execute(AUDIT_SCHEMA_SQL)
        conn.execute("truncate table audit_chain_checkpoints restart identity")
        conn.execute("truncate table audit_events restart identity")
        conn.commit()


@pytest.mark.integration
def test_audit_enabled_runtime_writes_rows_and_trace_ids(monkeypatch):
    dsn = _require_postgres_dsn()
    monkeypatch.setenv("BPG_AUDIT_DATABASE_URL", dsn)
    _reset_audit_schema(dsn)

    process = parse_process_file(_FIXTURES / "enabled.bpg.yaml")
    validate_process(process)
    process = process.model_copy(
        update={
            "observability": process.observability.model_copy(
                update={
                    "audit": process.observability.audit.model_copy(update={"dsn": dsn}),
                    "tracing": {"enabled": True, "exporter": "none"},
                }
            )
        }
    )
    ir = compile_process(process)
    mock = MockProvider()
    mock.set_default({"ok": True})
    runtime = LangGraphRuntime(
        ir=ir,
        providers={"mock": mock},
        event_sink=build_runtime_event_sink(process),
    )
    run_id = f"integration-{uuid4()}"
    runtime.run(input_payload={"text": "hello"}, run_id=run_id)

    sink = PostgresAuditEventSink(dsn=dsn)
    rows = sink.fetch_run_records(run_id)
    assert rows
    assert sink.verify_run(run_id).ok is True
    started = next(row for row in rows if row["event_type"] == "run_started")
    assert any(row.get("trace_id") for row in rows)
    assert started["trace_id"]


@pytest.mark.integration
def test_temporal_worker_integration_is_opt_in():
    target = os.getenv("BPG_TEST_TEMPORAL_TARGET")
    if not target:
        pytest.skip(
            "set BPG_TEST_TEMPORAL_TARGET to run Temporal traceability integration tests"
        )
    pytest.skip(
        "Temporal worker fixture not yet wired; tracked for follow-up worker harness"
    )
