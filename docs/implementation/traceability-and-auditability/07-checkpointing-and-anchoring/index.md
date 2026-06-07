# 7. Checkpointing and Anchoring

## Objective
Add audit chain checkpoints and optional external anchoring.

## Rationale
Hash chaining inside one mutable database is tamper-evident only when verifiers have a trusted prior chain head. Checkpoints summarize chain heads, and external anchors improve assurance.

## Primary Touchpoints
- Postgres audit schema.
- Audit verification helper.
- Runtime or maintenance job entrypoint.
- Optional anchoring provider module.
- Tests for checkpoint creation and verification.

## Scope
Create the checkpoint table:

```sql
create table audit_chain_checkpoints (
  checkpoint_id bigserial primary key,
  created_at timestamptz not null default now(),
  scope text not null,
  last_sequence_id bigint not null,
  chain_head_hash text not null,
  anchored_ref text,
  signature text
);
```

Initial checkpoint behavior:

- Compute a checkpoint from current per-run chain heads or the latest global summary.
- Store checkpoint rows in Postgres.
- Emit `audit_checkpointed` canonical events.
- Support verification from a checkpoint.

Optional first anchoring provider can be a signed local or object-storage checkpoint file. Keep provider configuration generic so S3 Object Lock, KMS-signed files, webhooks, or transparency logs can be added later.

## Implementation Tasks
1. Add checkpoint schema migration.
2. Implement checkpoint creation for current chain heads.
3. Add optional signature support if a signing key is configured.
4. Add an anchoring provider interface.
5. Implement one minimal provider or a no-op provider with explicit configuration.
6. Add verification that reports missing anchors as reduced assurance, not proof of tampering.
7. Add tests for checkpoint creation, checkpoint verification, and tampered chain detection after a checkpoint.

## Acceptance Criteria
- Checkpoints can be created without stopping workflow execution.
- Verification can start from genesis or from a checkpoint.
- Checkpoint rows include the last sequence ID and chain head hash.
- Anchor reference and signature are persisted when configured.
- Missing external anchors are clearly reported.
- Tampered events after a checkpoint fail verification.

## Verification
```bash
uv run pytest tests -k "audit and checkpoint"
```

Add an integration test if the first anchoring provider writes to an external service. Otherwise, unit-test the provider interface and local/signed-file behavior.

## Out of Scope
- CLI command implementation, except for any internal helper needed by tests.
- Marketplace verification node.
- Selecting a regulated production anchoring vendor.
