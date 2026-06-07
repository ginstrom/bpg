# Traceability Integration Tests

Opt-in tests under this directory exercise live Postgres (and optionally Temporal or OTLP
collector) services. They are skipped by default when required environment variables are
unset.

## Postgres audit ledger

Start a local Postgres instance:

```bash
docker run --rm --name bpg-audit-test \
  -e POSTGRES_PASSWORD=bpg \
  -e POSTGRES_USER=bpg \
  -e POSTGRES_DB=bpg \
  -p 55432:5432 \
  postgres:16
```

Run integration tests:

```bash
export BPG_TEST_POSTGRES_DSN=postgresql://bpg:bpg@localhost:55432/bpg
export BPG_AUDIT_DATABASE_URL="$BPG_TEST_POSTGRES_DSN"

uv run pytest tests/test_audit_postgres.py -m integration
uv run pytest tests/integration -m integration
```

## End-to-end runtime capture

The `test_traceability_e2e.py` module runs an audit-enabled process through
`LangGraphRuntime` with `build_runtime_event_sink`, then verifies hash chains and trace ID
projection into audit rows.

## Temporal worker path

Temporal integration is gated on `BPG_TEST_TEMPORAL_TARGET`. Until a shared local worker
fixture lands in CI, the test documents the contract and skips when the target is unset.

```bash
export BPG_TEST_TEMPORAL_TARGET=localhost:7233
uv run pytest tests/integration -m integration -k temporal
```

## Optional OTLP collector

Set `BPG_TEST_OTEL_ENDPOINT` to point at a collector when validating remote export. The
default integration path uses in-memory exporters and does not require a collector.
