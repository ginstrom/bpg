# 17. Operator Documentation

## Objective
Document deployment and operations guidance needed to run traceability features safely in production.

## Rationale
Implementation step 4 called for append-only database role guidance. The codebase enforces immutability with triggers, but operators still need explicit instructions for roles, environment variables, failure policies, checkpointing, and the distinction between runtime capture and marketplace helper nodes.

## Primary Touchpoints
- `docs/cli/audit.md`
- `docs/cli/trace.md`
- `docs/reference/process_schema.md`
- `docs/marketplace/audit-helper-nodes.md`
- New page under `docs/operations/` or `docs/guides/`
- `README.md` documentation map

## Scope

### In scope
- Postgres operator guide covering:
  - recommended schema setup / migration entrypoint
  - application role with `insert` + `select` only
  - separate schema owner role
  - trigger-backed append-only behavior as defense in depth
  - backup/WAL note (high level)
  - `BPG_AUDIT_DATABASE_URL` and `observability.audit.dsn_env`
- Runbook sections:
  - choosing `failure_policy` (`fail_run` vs `warn`)
  - choosing `payload_retention`
  - creating and verifying checkpoints
  - interpreting missing external anchors as reduced assurance
- Clarify runtime vs marketplace responsibilities.
- Clarify relationship between legacy `policy.audit` retention/export tags and `observability.audit` durable capture.

### Out of scope
- Vendor-specific regulated anchoring runbooks (S3 Object Lock, KMS, transparency log).
- Full OpenTelemetry collector deployment guide (link to external docs).

## Implementation Tasks

1. Add `docs/operations/audit-ledger.md` (or equivalent) with role SQL examples based on design doc triggers and table definitions.

2. Add `docs/operations/tracing.md` with minimal OTLP endpoint configuration examples.

3. Cross-link from:
   - `docs/cli/audit.md`
   - `docs/reference/process_schema.md`
   - `docs/marketplace/audit-helper-nodes.md`
   - `README.md`

4. Add a short troubleshooting section:
   - audit sink unavailable
   - hash verification failure
   - trace ID missing in audit rows
   - helper node failures vs runtime capture failures

5. Include copy-paste examples for the audit-enabled fixture process.

## Acceptance Criteria
- Operators can configure Postgres audit capture without reading source code.
- Role guidance explains why update/delete are denied.
- Docs clearly state marketplace nodes are optional and not required for capture.
- README documentation map links to the new operations pages.

## Verification

Manual doc review checklist:

- [ ] Enable audit on a fixture process using documented env vars.
- [ ] Inspect and verify a run using documented CLI commands.
- [ ] Create a checkpoint using documented commands after workstream 14 lands.
- [ ] Follow role-setup SQL in a fresh local Postgres instance.

## Dependencies
- [14. Checkpoint Operations](14-checkpoint-operations/index.md) for checkpoint runbook steps.
- [10. Runtime Sink Integration](10-runtime-sink-integration/index.md) so operational docs match actual runtime behavior.
