# CLI: bpg trace

```yaml
doc_metadata:
  topic: cli_trace
  version: 1
  summary: Correlate audit records with OpenTelemetry trace and span identifiers.
```

## Summary
`bpg trace show` reads trace and span IDs captured in the Postgres audit ledger so operators can search an OpenTelemetry backend for the same run.

## When to use
Use after a run completes when you need the root trace ID, root span ID, per-node span IDs, and the configured exporter target for log or trace backend lookup.

## Required environment
Trace correlation is derived from audit rows, so Postgres access is required:

- `--dsn postgresql://...`
- `--dsn-env BPG_AUDIT_DATABASE_URL` (default) with the variable set in the shell

Example:

```bash
export BPG_AUDIT_DATABASE_URL=postgresql://bpg:bpg@localhost:55432/bpg
```

## Examples
```bash
# Human-readable trace correlation summary
uv run bpg trace show <run-id>

# Machine-readable trace correlation JSON
uv run bpg trace show <run-id> --json

# Resolve exporter target from a process definition
uv run bpg trace show <run-id> --process-file examples/wrappers/parse-sum-email/process.bpg.yaml
```

## Options
- `run_id`: Target run identifier.
- `--process-file`: Optional process definition used to resolve tracing exporter settings.
- `--dsn`: Postgres DSN for the audit ledger.
- `--dsn-env`: Environment variable containing the audit Postgres DSN (default: `BPG_AUDIT_DATABASE_URL`).
- `--json`: Emit structured JSON instead of human-readable output.

## Output fields
- `trace_id`: Root trace ID from the `run_started` audit event.
- `root_span_id`: Root span ID from the `run_started` audit event.
- `node_span_ids`: Map of node ID to span ID from node lifecycle events.
- `exporter_target`: OTLP endpoint when tracing is enabled in the process definition.

## Related pages
- [Tracing operations](../operations/tracing.md)
- [CLI: bpg audit](audit.md)
- [CLI: bpg replay](replay.md)
- [Traceability and Auditability Design](../design/traceability-and-auditability.md)
