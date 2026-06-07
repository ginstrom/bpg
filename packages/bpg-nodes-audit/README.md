# bpg-nodes-audit

Optional marketplace helper nodes for audit export, verification, compliance reporting, and evidence routing.

These nodes read from the runtime Postgres audit ledger. They do not replace mandatory runtime audit capture.

## Nodes

- `audit.export_bundle` — export a deterministic audit evidence bundle for one run
- `audit.verify_chain` — verify hash-chain integrity for one run
- `audit.write_compliance_summary` — render a compliance summary from audit evidence
- `audit.notify_compliance_channel` — route a compliance summary to Slack, email, or webhook
- `audit.create_case` — open a compliance case ticket for one run
- `audit.attach_evidence` — attach exported evidence to an existing case

## Requirements

Postgres audit access is required for nodes that query the ledger. Provide a DSN with either:

- `dsn` in the node input payload
- `BPG_AUDIT_DATABASE_URL` in the environment
