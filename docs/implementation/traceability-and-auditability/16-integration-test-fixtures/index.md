# 16. Integration Test Fixtures

## Objective
Add opt-in integration tests and documented local setup for live Postgres and Temporal verification of traceability features.

## Rationale
The original plan intentionally deferred live service tests. Unit tests and mocked Temporal context provide good coverage, but the design verification strategy also calls for:

- Postgres append-only and hash-chain behavior against a real database.
- Temporal metadata attachment in a live worker path.
- Trace span structure matching run/node shape in an integration environment.

## Primary Touchpoints
- `tests/test_audit_postgres.py` (existing opt-in Postgres test)
- `tests/test_temporal_metadata.py`
- `tests/test_observability.py`
- New files under `tests/integration/` or package-specific integration dirs
- `docs/implementation/traceability-and-auditability/follow-up.md` (verification commands)
- Optional `docker-compose` or README snippet for local services

## Scope

### In scope
- Standardize environment conventions:
  - `BPG_TEST_POSTGRES_DSN` for Postgres audit integration (already used).
  - `BPG_TEST_TEMPORAL_TARGET` or reuse existing Temporal dev service conventions if present.
  - `BPG_TEST_OTEL_ENDPOINT` for optional collector verification.
- Add integration tests marked `@pytest.mark.integration`.
- Document startup commands and required env vars beside the tests.
- Add one end-to-end test path after workstream 10:
  - Run audit-enabled process.
  - Assert audit rows exist.
  - Verify hash chain.
  - Assert trace IDs appear in audit rows when tracing is enabled.

### Out of scope
- Managed cloud test infrastructure.
- CI requirement to run integration tests on every PR (keep opt-in).

## Implementation Tasks

1. Review existing Postgres integration test and expand assertions if needed:
   - update/delete trigger rejection
   - duplicate `event_id` behavior
   - checkpoint verify path

2. Add Temporal integration test once a local worker fixture exists:
   - workflow and activity IDs on execution log and canonical events
   - optional audit row correlation after workstream 12

3. Add optional OTLP collector fixture test using a lightweight in-process or containerized collector.

4. Add a short "Local integration setup" section to this doc or a nearby README.

5. Wire `pytest` marker documentation if not already present.

## Acceptance Criteria
- Integration tests are skipped by default and runnable with documented env vars.
- At least one live Postgres test validates append-only behavior and hash verification.
- Temporal integration test exists or is explicitly blocked behind a tracked fixture issue with mocked fallback retained.
- Follow-up verification commands in `follow-up.md` are reproducible by an engineer with local services.

## Local Integration Setup

See [tests/integration/README.md](../../../../tests/integration/README.md) for Docker
startup commands and environment variable conventions.

Standard variables:

- `BPG_TEST_POSTGRES_DSN` — Postgres audit integration (also sets `BPG_AUDIT_DATABASE_URL` in e2e tests).
- `BPG_TEST_TEMPORAL_TARGET` — Temporal dev service target (integration test skips until worker fixture lands).
- `BPG_TEST_OTEL_ENDPOINT` — Optional OTLP collector endpoint for remote export verification.

## Verification

```bash
# Postgres
export BPG_TEST_POSTGRES_DSN=postgresql://bpg:bpg@localhost:55432/bpg
export BPG_AUDIT_DATABASE_URL="$BPG_TEST_POSTGRES_DSN"
uv run pytest tests/test_audit_postgres.py -m integration

# End-to-end runtime capture
uv run pytest tests/integration -m integration

# Full opt-in suite
uv run pytest -m integration
```

## Dependencies
- [10. Runtime Sink Integration](10-runtime-sink-integration/index.md) for meaningful end-to-end audit emission tests.
- [12. Audit Correlation Projection](12-audit-correlation-projection/index.md) for Temporal fields in audit rows.
