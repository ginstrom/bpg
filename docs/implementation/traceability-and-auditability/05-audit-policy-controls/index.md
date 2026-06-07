# 5. Audit Policy Controls

## Objective
Add process and runtime policy controls for audit sink behavior, retention intent, payload retention, redaction, tags, and failure handling.

## Rationale
Audit capture belongs in the runtime, but deployments need explicit control over what is stored and what happens if audit storage fails.

## Primary Touchpoints
- Process schema and validation modules.
- `docs/reference/process_schema.md`
- Runtime configuration loading.
- Audit sink registration.
- Tests for schema validation and runtime policy.

## Scope
Add configuration for:

```yaml
observability:
  audit:
    enabled: true
    sink: postgres
    dsn_env: BPG_AUDIT_DATABASE_URL
    failure_policy: fail_run
    retention: regulated
    payload_retention: redacted
    redaction_policy_id: default
    tags:
      environment: production
      data_classification: confidential
```

Recommended `failure_policy` values:

```text
fail_run
warn
disabled
```

Recommended `payload_retention` values:

```text
hash_only
redacted
full
```

## Implementation Tasks
1. Extend the process/runtime configuration model.
2. Validate allowed audit policy values.
3. Apply redaction before audit events are passed to durable sinks.
4. Record `redaction_policy_id`, redacted field paths, and audit tags on canonical events.
5. Enforce full payload retention only when explicitly configured.
6. Wire `failure_policy` into audit sink error handling.
7. Update process schema docs with the new audit policy shape.

## Acceptance Criteria
- Invalid audit config fails validation with a clear diagnostic.
- `hash_only`, `redacted`, and `full` policies produce distinct stored payload behavior.
- `fail_run` causes workflow failure when the audit sink fails.
- `warn` records/logs the audit failure without failing the run.
- `disabled` does not configure the durable audit sink.
- Tracing still defaults to no raw input/output attributes.

## Verification
```bash
uv run pytest tests -k "audit and policy"
uv run bpg doctor examples/wrappers/parse-sum-email/process.bpg.yaml
```

Add at least one fixture process with audit policy enabled and one with invalid audit policy values.

The Postgres audit ledger integration test from step 4 is intentionally opt-in. It is skipped unless `BPG_TEST_POSTGRES_DSN` is set, for example to a local `postgres:16` test container. Keep policy-control integration tests consistent with that convention unless the repository adds a managed Postgres fixture.

## Out of Scope
- New marketplace nodes.
- External checkpoint anchoring.
- Temporal metadata extraction.
