# Postgres Audit Ledger Operations

```yaml
doc_metadata:
  topic: operations_audit_ledger
  version: 1
  summary: Operator guidance for durable audit capture, roles, checkpoints, and troubleshooting.
```

## Overview

BPG writes tamper-evident audit records during `bpg run` when a process enables
`observability.audit`. Runtime capture is mandatory for compliance evidence. The
`bpg-nodes-audit` marketplace package provides optional post-run reporting helpers and does
not replace runtime capture.

Legacy `policy.audit` retention and export tags describe run-log retention policy. Durable
evidence lives under `observability.audit` and the Postgres ledger.

## Schema setup

Apply the audit schema before enabling capture. The schema ships in
`bpg.audit.postgres.AUDIT_SCHEMA_SQL` and is applied automatically on first sink use. For
manual bootstrap:

```bash
export BPG_AUDIT_DATABASE_URL=postgresql://bpg_runtime:...@localhost:5432/bpg
psql "$BPG_AUDIT_DATABASE_URL" -c "$(uv run python -c 'from bpg.audit import AUDIT_SCHEMA_SQL; print(AUDIT_SCHEMA_SQL)')"
```

Tables:

- `audit_events` — append-only hash-chained event rows.
- `audit_chain_checkpoints` — chain head snapshots for faster verification and anchoring.

## Database roles

Use separate roles for schema ownership and runtime capture.

```sql
-- Schema owner (migrations only)
create role bpg_audit_owner login password '...';
create schema audit authorization bpg_audit_owner;

-- Application runtime (insert + select only)
create role bpg_runtime login password '...';
grant usage on schema audit to bpg_runtime;
grant insert, select on audit.audit_events to bpg_runtime;
grant insert, select on audit.audit_chain_checkpoints to bpg_runtime;
grant usage, select on all sequences in schema audit to bpg_runtime;
```

Append-only triggers reject `update` and `delete` even if a role is misconfigured:

```sql
create function audit.prevent_audit_mutation()
returns trigger language plpgsql as $$
begin
  raise exception 'audit_events is append-only';
end;
$$;

create trigger audit_events_no_update
before update on audit.audit_events
for each row execute function audit.prevent_audit_mutation();
```

Enable WAL archiving and regular backups. Checkpoints and optional external anchors provide
additional tamper evidence outside the database.

## Process configuration

Enable capture on a process definition:

```yaml
observability:
  audit:
    enabled: true
    sink: postgres
    dsn_env: BPG_AUDIT_DATABASE_URL
    failure_policy: warn
    payload_retention: redacted
    tags:
      environment: production
```

Environment variables:

- `BPG_AUDIT_DATABASE_URL` — default DSN when `dsn_env` is unset.
- Process-level `observability.audit.dsn_env` — override the environment variable name.

### Failure policy

| Policy | Behavior |
| --- | --- |
| `warn` | Log audit sink failures; run continues (default). |
| `fail_run` | Abort the run when durable audit capture fails. |
| `disabled` | Do not register the Postgres audit sink. |

Use `fail_run` in regulated environments where missing evidence must block execution.

### Payload retention

| Mode | Stored payload |
| --- | --- |
| `redacted` | Redacted event payload plus `_audit` metadata (default). |
| `hash_only` | `_audit` metadata and payload hash only. |
| `full` | Original payload; must be explicitly configured. |

## Operator workflow

```bash
export BPG_AUDIT_DATABASE_URL=postgresql://bpg_runtime:...@localhost:5432/bpg

# Run an audit-enabled fixture process
uv run bpg run audit-policy-enabled \
  --process-file tests/fixtures/audit_policy/enabled.bpg.yaml \
  --input '{"text":"hello"}' \
  --engine local

# Inspect and verify
uv run bpg audit show <run-id>
uv run bpg audit verify <run-id>
uv run bpg audit export <run-id> --output /tmp/bpg-audit-bundle.json

# Create a checkpoint
uv run bpg audit checkpoint create --scope run:<run-id> --json
uv run bpg audit verify <run-id> --from-checkpoint
```

Missing external anchors reduce assurance; they are not proof of tampering. Tampered rows
after a checkpoint fail verification.

## Runtime vs marketplace

| Concern | Runtime capture | Marketplace helpers |
| --- | --- | --- |
| When | During `bpg run` | Post-run workflows |
| Required | Yes, when audit is enabled | No |
| Writes ledger | Yes | Read-only (export/verify/report) |

## Troubleshooting

**Audit sink unavailable**

- Confirm `BPG_AUDIT_DATABASE_URL` or `dsn_env` is set and reachable.
- Check runtime logs for `Postgres audit event insert failed`.
- With `failure_policy: fail_run`, the run aborts; with `warn`, capture is best-effort.

**Hash verification failure**

- Re-export the bundle and inspect `verification.message`.
- Compare `payload_sha256` and `event_hash` mismatches for the first failing sequence ID.
- If verifying from a checkpoint, ensure no rows were altered after the checkpoint.

**Trace ID missing in audit rows**

- Tracing must be enabled (`observability.tracing.enabled: true`).
- OpenTelemetry export is best-effort; trace IDs are projected when the tracing sink runs
  before the audit sink in the runtime event group.

**Helper node failures vs runtime capture**

- Marketplace node failures do not retroactively create audit evidence.
- Fix helper configuration for reporting; rely on runtime capture for durable records.

## Related pages

- [CLI: bpg audit](../cli/audit.md)
- [CLI: bpg trace](../cli/trace.md)
- [Process schema: observability](../reference/process_schema.md)
- [Audit helper nodes](../marketplace/audit-helper-nodes.md)
- [Traceability design](../design/traceability-and-auditability.md)
