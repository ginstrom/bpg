# 14. Checkpoint Operations

## Objective
Give operators a supported way to create audit chain checkpoints and optional external anchors outside test-only APIs.

## Rationale
Step 7 implemented `PostgresAuditEventSink.create_checkpoint()`, signature support, anchoring providers, and verification from checkpoints. Operators can verify and export from checkpoints via CLI flags, but there is no command or maintenance entrypoint to create them.

## Primary Touchpoints
- `src/bpg/audit/postgres.py`
- `src/bpg/cli.py`
- `docs/cli/audit.md`
- `tests/test_cli_audit.py`
- `tests/test_audit_postgres.py`

## Scope

### In scope
- CLI command(s) for checkpoint creation, for example:
  - `bpg audit checkpoint create --scope run:<run-id>`
  - `bpg audit checkpoint create --scope global` (if global summaries are supported)
- Optional flags:
  - `--anchor-provider local-file --anchor-dir <path>`
  - `--signing-key-env <env>`
  - `--json`
- Emit `audit_checkpointed` canonical event when checkpoint creation is invoked from runtime/maintenance context (if not already emitted by API callers).
- Document checkpoint operations and anchor expectations.

### Out of scope
- New anchoring vendors beyond the existing local-file and no-op providers.
- Scheduled/automatic checkpoint cron deployment (document as operator responsibility).

## Implementation Tasks

1. Add CLI handler(s) that resolve the audit sink and call `create_checkpoint()`.

2. Return structured output:
   - `checkpoint_id`
   - `scope`
   - `last_sequence_id`
   - `chain_head_hash`
   - `anchored_ref`
   - `signature`

3. Wire optional anchoring provider selection from CLI flags or environment variables.

4. Add CLI tests for:
   - Successful checkpoint creation.
   - Missing DSN.
   - Anchor present vs missing with `--require-anchor` on subsequent verify/export.

5. Update `docs/cli/audit.md` and cross-link from follow-up verification examples.

## Acceptance Criteria
- Operators can create a checkpoint without stopping workflow execution.
- Created checkpoint rows include `last_sequence_id` and `chain_head_hash`.
- `bpg audit verify <run-id> --from-checkpoint` succeeds against a run with a prior checkpoint.
- Missing external anchors are reported as reduced assurance, not proof of tampering.
- Tampered rows after a checkpoint fail verification.

## Verification

```bash
uv run pytest tests/test_cli_audit.py tests/test_audit_postgres.py -k "checkpoint"
uv run bpg audit checkpoint create --scope run:<run-id>
uv run bpg audit verify <run-id> --from-checkpoint
```

## Dependencies
- Requires Postgres audit sink availability.
- Most useful after [10. Runtime Sink Integration](10-runtime-sink-integration/index.md) populates audit rows in real runs.
