# Audit Helper Nodes

```yaml
doc_metadata:
  topic: marketplace_audit_helper_nodes
  version: 1
  summary: Optional marketplace nodes for audit export, verification, and compliance reporting.
```

## Summary

The `bpg-nodes-audit` package provides optional helper nodes for post-run compliance workflows. They read from the runtime Postgres audit ledger and must not be used as the primary audit capture mechanism.

Runtime capture remains mandatory and independent of these nodes.

## Package

```text
bpg.nodes.audit@v1
```

Install in a workspace:

```bash
uv add bpg-nodes-audit
```

## Nodes

| Node | Purpose |
| --- | --- |
| `audit.export_bundle` | Export a deterministic JSON evidence bundle for one run |
| `audit.verify_chain` | Recompute and verify hash chains for one run |
| `audit.write_compliance_summary` | Build a markdown or JSON compliance summary from audit rows |
| `audit.notify_compliance_channel` | Send a compliance summary to Slack, email, or webhook |
| `audit.create_case` | Open a compliance case for one audited run |
| `audit.attach_evidence` | Attach an exported bundle or hash reference to a case |

## Required Configuration

All nodes that query the ledger accept:

```yaml
dsn: postgres://user:pass@host:5432/audit
dsn_env: BPG_AUDIT_DATABASE_URL
```

If neither is provided, nodes read `BPG_AUDIT_DATABASE_URL` from the environment.

## Example Composition

See [examples/audit/compliance-report/README.md](../../examples/audit/compliance-report/README.md).

Typical post-run flow:

```text
audit.verify_chain -> audit.export_bundle -> audit.write_compliance_summary -> audit.notify_compliance_channel
```

## Dry Run

Pass `dry_run: true` in node inputs to validate routing without external side effects.

## Related Pages

- [CLI: audit](../cli/audit.md)
- [CLI: trace](../cli/trace.md)
- [Traceability and Auditability Design](../design/traceability-and-auditability.md)
