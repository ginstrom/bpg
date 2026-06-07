# CLI: bpg audit

```yaml
doc_metadata:
  topic: cli_audit
  version: 1
  summary: Inspect, verify, and export tamper-evident audit records from the Postgres ledger.
```

## Summary
`bpg audit` commands query the durable Postgres audit ledger for one run, verify hash-chain integrity, and export an evidence bundle for auditors.

## When to use
Use when you need to inspect evidentiary records, prove that audit rows were not tampered with, or export a deterministic bundle for offline review.

## Required environment
Postgres access is required for all audit commands. Provide a connection string with either:

- `--dsn postgresql://...`
- `--dsn-env BPG_AUDIT_DATABASE_URL` (default) with the variable set in the shell

Example:

```bash
export BPG_AUDIT_DATABASE_URL=postgresql://bpg:bpg@localhost:55432/bpg
```

## Examples
```bash
# Human-readable audit event list
uv run bpg audit show <run-id>

# Machine-readable audit events
uv run bpg audit show <run-id> --json

# Verify hash-chain integrity (non-zero exit on mismatch)
uv run bpg audit verify <run-id>

# Export an evidence bundle
uv run bpg audit export <run-id> --output /tmp/bpg-audit-bundle.json

# Create a run-scoped checkpoint
uv run bpg audit checkpoint create --scope run:<run-id> --json

# Create a checkpoint with a local-file anchor
uv run bpg audit checkpoint create --scope run:<run-id> \
  --anchor-provider local-file --anchor-dir /tmp/bpg-audit-anchors
```

## Commands
### `bpg audit show <run-id>`
Print ordered audit events with sequence ID, event type, timestamp, node, actor, trace ID, and event hash.

### `bpg audit verify <run-id>`
Recompute payload and event hashes for the run-scoped chain. Returns a non-zero exit code when a mismatch is detected.

### `bpg audit export <run-id> --output <path>`
Write a deterministic JSON bundle containing audit rows, checkpoint data, process hash/version, trace IDs, verification results, and optional Temporal identifiers found in payloads.

### `bpg audit checkpoint create --scope <scope>`
Create an audit chain checkpoint for `run:<run-id>` or `global`. Returns checkpoint ID, chain head hash, optional anchor reference, and signature.

## Options
- `run_id`: Target run identifier.
- `--dsn`: Postgres DSN for the audit ledger.
- `--dsn-env`: Environment variable containing the audit Postgres DSN (default: `BPG_AUDIT_DATABASE_URL`).
- `--json`: Emit structured JSON instead of human-readable output (`show`, `verify`; `export` prints the bundle to stdout).
- `--from-checkpoint`: Verify or export using only rows after the latest `run:<run-id>` checkpoint.
- `--require-anchor`: Fail when the latest checkpoint has no external anchor reference.
- `--output` / `-o`: Output path for `audit export`.
- `--scope`: Checkpoint scope (`run:<run-id>` or `global`) for `audit checkpoint create`.
- `--anchor-provider`: External anchor provider (`none` or `local-file`).
- `--anchor-dir`: Directory for `local-file` anchors.
- `--signing-key-env`: Environment variable containing the checkpoint signing key.

## Related pages
- [CLI: bpg trace](trace.md)
- [CLI: bpg replay](replay.md)
- [Traceability and Auditability Design](../design/traceability-and-auditability.md)
