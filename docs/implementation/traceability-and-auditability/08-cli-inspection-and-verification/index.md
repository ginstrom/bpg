# 8. CLI Inspection and Verification

## Objective
Add CLI commands for audit inspection, hash-chain verification, audit bundle export, and trace correlation.

## Rationale
Operators and auditors need practical tools to inspect the ledger, prove chain integrity, export evidence, and correlate audit records with traces and Temporal history.

## Primary Touchpoints
- CLI command modules.
- `docs/cli/`
- Postgres audit query helpers.
- Audit verification helper.
- Tests for CLI behavior.

## Scope
Add or extend commands for:

```text
bpg audit show <run-id>
bpg audit verify <run-id>
bpg audit export <run-id> --output <path>
bpg trace show <run-id>
```

Suggested output behavior:

- `audit show`: print ordered audit events with sequence ID, event type, timestamp, node, actor, trace ID, and event hash.
- `audit verify`: recompute hashes and return non-zero exit on mismatch.
- `audit export`: write a bundle containing audit rows, checkpoint data, process hash/version, trace IDs, and optional Temporal IDs.
- `trace show`: print trace ID, root span ID, node span IDs, and configured exporter target when known.

## Implementation Tasks
1. Add audit query functions for run-scoped event retrieval.
2. Add CLI parser entries and command handlers.
3. Add JSON output flags if existing CLI conventions support them.
4. Add audit bundle export format.
5. Add docs under `docs/cli/`.
6. Update README documentation map if new CLI pages are added.
7. Add CLI tests for success, missing run, and verification failure.

## Acceptance Criteria
- Operators can inspect audit records for one run.
- Hash-chain verification fails with a non-zero exit code on tampering.
- Export bundles are deterministic for unchanged audit data.
- Trace correlation output includes enough IDs to search an OTel backend.
- CLI docs include required environment variables for Postgres access.

## Verification
```bash
uv run pytest tests -k "cli and audit"
uv run bpg audit verify <run-id>
uv run bpg audit export <run-id> --output /tmp/bpg-audit-bundle.json
uv run bpg trace show <run-id>
```

## Out of Scope
- Building a web UI.
- Marketplace reporting nodes.
- New anchoring providers.
