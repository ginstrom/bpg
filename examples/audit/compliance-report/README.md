# Compliance Report Example

This example composes optional audit helper nodes as post-run reporting steps.

Runtime audit capture happens automatically during `bpg run`. The nodes in this process only read, verify, export, and route evidence from the Postgres audit ledger.

## Workflow

```text
ingest -> audit.verify_chain -> audit.export_bundle -> audit.write_compliance_summary
      -> audit.notify_compliance_channel -> audit.create_case -> audit.attach_evidence
```

## Prerequisites

- A completed run with audit records in Postgres
- `BPG_AUDIT_DATABASE_URL` configured, or pass `dsn` in node inputs

## Validate

```bash
uv run python -m bpg_cli.main validate examples/audit/compliance-report/process.v2.bpg.yaml
```

## Notes

- Helper nodes are optional. Skipping this process does not disable runtime audit capture.
- Use `dry_run: true` in node inputs to exercise routing without writing files or sending notifications.
