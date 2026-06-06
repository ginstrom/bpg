# 9. Marketplace Helper Nodes

## Objective
Add optional marketplace nodes that help users compose compliance and reporting workflows on top of runtime audit capture.

## Rationale
Marketplace nodes are useful for export, notification, case creation, and verification workflows. They must not be required for mandatory runtime audit capture because users could omit or bypass them.

## Primary Touchpoints
- `packages/bpg-sdk/src/bpg_sdk/marketplace.py`
- `packages/bpg-sdk/src/bpg_sdk/manifest.py`
- Marketplace package or examples directories.
- Docs for marketplace node usage.
- Tests for node manifests and behavior.

## Scope
Consider these helper nodes:

```text
export_audit_bundle
write_compliance_summary
notify_compliance_channel
create_audit_case
attach_evidence_to_ticket
verify_audit_chain
```

Do not implement nodes that try to become primary capture, such as:

```text
log_every_node_to_audit
record_approval_for_compliance
trace_workflow
```

## Implementation Tasks
1. Define manifests for selected helper nodes.
2. Implement node handlers using the CLI/query/audit helper APIs from earlier steps.
3. Add examples that compose helper nodes after normal workflow execution.
4. Add schema validation tests for node manifests.
5. Add behavior tests using fixture audit records.
6. Document that runtime capture remains mandatory and independent of these nodes.

## Acceptance Criteria
- Helper nodes can export, verify, or route audit evidence without duplicating runtime capture.
- Node manifests advertise clear inputs and outputs.
- Nodes fail clearly when audit storage is unavailable.
- Examples show helper nodes as post-run/reporting workflow steps.
- Tests prove helper nodes do not create core audit lifecycle records themselves.

## Verification
```bash
uv run pytest packages tests -k "marketplace and audit"
uv run bpg doctor <example-process-with-audit-helper-node>.bpg.yaml
```

## Out of Scope
- Runtime event capture.
- Postgres schema changes.
- OpenTelemetry exporter behavior.
