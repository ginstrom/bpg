# Traceability and Auditability Follow-Up Plan

This plan closes the gaps between the completed implementation steps (1–9) and the production-ready behavior described in [Traceability and Auditability Design](../../design/traceability-and-auditability.md).

Steps 1–9 delivered the canonical event model, sink abstractions, Postgres ledger, policy controls, CLI tooling, and marketplace helper nodes. The follow-up work focuses on **runtime integration**, **correlation metadata completeness**, **event coverage**, and **operator ergonomics**.

## Background

A completeness review against the design and implementation checklist found:

- Core libraries, schemas, tests, CLI commands, and marketplace nodes are in place.
- `LangGraphRuntime` emits canonical events, but production backends (`LangGraphExecutionBackend`, `TemporalRuntime`) do not pass a configured observability sink. They default to `NoopEventSink`, so Postgres audit and OpenTelemetry export are not active during normal `bpg run` execution.
- Temporal correlation fields and payload hashes exist on `BpgEvent`, but are not consistently projected into durable audit rows.
- Several canonical event types are defined but not emitted by runtime paths.
- Workspace hygiene tests fail because `bpg-nodes-audit` is not yet registered in framework layout expectations.

## Delivery Principles

Carry forward the principles from the original plan:

- Runtime capture remains mandatory for core tracing and audit events.
- Marketplace nodes remain optional reporting helpers.
- OpenTelemetry export stays best-effort.
- Audit sink failures follow configured `failure_policy`.
- Redaction and hashing happen before events leave the runtime boundary.

## Workstreams

Deliver in order. Later items assume earlier contracts are merged.

| Priority | Workstream | Blocks |
|----------|------------|--------|
| P0 | [10. Runtime Sink Integration](10-runtime-sink-integration/index.md) | End-to-end audit and tracing during `bpg run` |
| P0 | [11. Workspace and Package Hygiene](11-workspace-and-package-hygiene/index.md) | Clean CI after step 9 |
| P1 | [12. Audit Correlation Projection](12-audit-correlation-projection/index.md) | Temporal and hash correlation in audit evidence |
| P1 | [13. Lifecycle Event Coverage](13-lifecycle-event-coverage/index.md) | Full canonical event type emission |
| P2 | [14. Checkpoint Operations](14-checkpoint-operations/index.md) | Operator checkpoint creation |
| P2 | [15. Tracing Enhancements](15-tracing-enhancements/index.md) | Span links and Temporal trace propagation |
| P3 | [16. Integration Test Fixtures](16-integration-test-fixtures/index.md) | Live Postgres and Temporal verification |
| P3 | [17. Operator Documentation](17-operator-documentation/index.md) | Database roles and runbook guidance |

## Checklist

- [x] [10. Runtime Sink Integration](10-runtime-sink-integration/index.md)
- [x] [11. Workspace and Package Hygiene](11-workspace-and-package-hygiene/index.md)
- [x] [12. Audit Correlation Projection](12-audit-correlation-projection/index.md)
- [x] [13. Lifecycle Event Coverage](13-lifecycle-event-coverage/index.md)
- [x] [14. Checkpoint Operations](14-checkpoint-operations/index.md)
- [x] [15. Tracing Enhancements](15-tracing-enhancements/index.md)
- [x] [16. Integration Test Fixtures](16-integration-test-fixtures/index.md)
- [ ] [17. Operator Documentation](17-operator-documentation/index.md)

## Suggested Milestones

### Milestone A — Production capture works

Complete workstreams **10** and **11**.

Outcome: a process with `observability.audit.enabled: true` and a valid DSN writes hash-chained rows during `bpg run`. Enabled tracing exports spans without failing the run. CI is green.

### Milestone B — Evidence is complete

Complete workstreams **12** and **13**.

Outcome: audit bundles and `bpg audit show` include Temporal identifiers and input/output hashes where available. Runtime emits approval, edge, and scheduling events aligned with the canonical contract.

### Milestone C — Operator-ready

Complete workstreams **14**, **16**, and **17**.

Outcome: operators can create checkpoints, verify chains from anchors, and follow documented Postgres role guidance. Opt-in integration tests cover live services.

### Milestone D — Advanced tracing

Complete workstream **15** when Temporal cross-boundary propagation is prioritized.

Outcome: trace context and span links improve backend correlation without changing audit semantics.

## Cross-Workstream Verification

Run after Milestone A:

```bash
uv run pytest
uv run bpg doctor tests/fixtures/audit_policy/enabled.bpg.yaml
```

With Postgres available:

```bash
export BPG_AUDIT_DATABASE_URL=postgresql://bpg:bpg@localhost:55432/bpg
export BPG_TEST_POSTGRES_DSN="$BPG_AUDIT_DATABASE_URL"

uv run pytest tests/test_audit_postgres.py -k integration
uv run bpg run <audit-enabled-process> --engine local
uv run bpg audit show <run-id>
uv run bpg audit verify <run-id>
uv run bpg trace show <run-id>
```

Run after Milestone B:

```bash
uv run pytest tests -k "temporal or audit or observability"
uv run bpg audit export <run-id> --output /tmp/bpg-audit-bundle.json
```

## Out of Scope

- Replacing Postgres with an external compliance ledger.
- Building a web UI for audit inspection.
- Selecting a regulated production anchoring vendor.
- Making OpenTelemetry traces compliance evidence.
- Resolving open design questions (audit failure default in production, global chain from day one, first-party external anchor) unless a follow-up ADR is written.

## Related Pages

- [Traceability and Auditability Design](../../design/traceability-and-auditability.md)
- [Original Implementation Plan](index.md)
- [Audit CLI](../../cli/audit.md)
- [Trace CLI](../../cli/trace.md)
- [Audit Helper Nodes](../../marketplace/audit-helper-nodes.md)
