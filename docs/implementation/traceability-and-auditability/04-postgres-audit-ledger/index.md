# 4. Postgres Audit Ledger

## Objective
Implement a Postgres audit sink that writes append-only, hash-chained audit records.

## Rationale
Audit is evidentiary record keeping. It must be durable, tamper-evident, and independent of best-effort tracing.

## Primary Touchpoints
- New audit persistence module under `src/bpg/` or an audit package selected by maintainers.
- Runtime sink registration.
- Database migration or schema setup files.
- Tests with a local Postgres fixture or container.

## Scope
Create the `audit_events` table from the design:

```sql
create table audit_events (
  sequence_id bigserial primary key,
  chain_scope text not null,
  chain_id text not null,
  event_id text not null unique,
  event_type text not null,
  occurred_at timestamptz not null,
  inserted_at timestamptz not null default now(),

  run_id text not null,
  process_name text not null,
  process_version text,
  process_hash text,
  node_id text,
  node_type text,

  actor_id text,
  actor_type text,
  policy_id text,
  correlation_id text,
  external_ref text,

  trace_id text,
  span_id text,

  payload jsonb not null,
  payload_sha256 text not null,
  previous_hash text,
  event_hash text not null
);
```

Recommended initial chain:

```text
chain_scope = run
chain_id = run_id
```

Hash formula:

```text
payload_sha256 = sha256(canonical_json(redacted_payload))

event_hash = sha256(canonical_json({
  previous_hash,
  chain_scope,
  chain_id,
  sequence_id,
  event_id,
  event_type,
  occurred_at,
  run_id,
  process_name,
  process_version,
  process_hash,
  node_id,
  node_type,
  actor_id,
  policy_id,
  correlation_id,
  external_ref,
  trace_id,
  span_id,
  payload_sha256
}))
```

## Implementation Tasks
1. Add Postgres dependency using `uv`.
2. Add schema creation or migration files.
3. Implement canonical JSON hashing.
4. Implement redacted payload hashing.
5. Insert audit rows inside a transaction that locks or serializes per-run chain head updates.
6. Add update/delete prevention triggers.
7. Add a verification helper that recomputes a run chain and reports the first mismatch.
8. Document recommended database roles: application role has `insert` and `select`, not `update` or `delete`.

## Acceptance Criteria
- Audit sink writes one row per audit-worthy canonical event.
- Hashes are deterministic and verifiable.
- Per-run chain order is stable under concurrent event emission for one run.
- Duplicate `event_id` insertion is rejected or idempotently handled with explicit behavior.
- Update and delete attempts fail because of database controls.
- Verification helper passes on untouched rows and fails after a deliberate mutation in test setup.

## Verification
```bash
uv run pytest tests -k "audit and postgres"
```

If Postgres integration tests require an external service, document the exact environment variables and service startup command in the test file or a nearby README.

## Out of Scope
- External anchoring.
- CLI commands for audit inspection.
- Global chain checkpointing.
