# Traceability and Auditability Implementation Plan

This plan implements the choices in [Traceability and Auditability Design](../../design/traceability-and-auditability.md).

The work should be delivered in order. Each step is self-contained enough to hand to an engineer, but later steps assume the contracts and tests from earlier steps are merged.

## Checklist
- [x] [1. Canonical Event Envelope](01-canonical-event-envelope/index.md)
- [x] [2. Runtime Sink Refactor](02-runtime-sink-refactor/index.md)
- [x] [3. OpenTelemetry Tracing](03-opentelemetry-tracing/index.md)
- [ ] [4. Postgres Audit Ledger](04-postgres-audit-ledger/index.md)
- [ ] [5. Audit Policy Controls](05-audit-policy-controls/index.md)
- [ ] [6. Temporal Metadata](06-temporal-metadata/index.md)
- [ ] [7. Checkpointing and Anchoring](07-checkpointing-and-anchoring/index.md)
- [ ] [8. CLI Inspection and Verification](08-cli-inspection-and-verification/index.md)
- [ ] [9. Marketplace Helper Nodes](09-marketplace-helper-nodes/index.md)

## Delivery Principles
- Runtime capture is mandatory for core tracing and audit events.
- Marketplace nodes are optional reporting and export helpers, not primary capture.
- OpenTelemetry traces are operational telemetry and must be best-effort.
- Audit records are evidentiary records and must follow the configured failure policy.
- Temporal metadata enriches BPG events but does not define the event contract.
- Payload redaction and hashing happen before events leave the runtime boundary.

## Target Architecture
```text
BPG runtime semantics
  -> canonical BPG event envelope
    -> local events.jsonl replay log
    -> OpenTelemetry trace exporter
    -> Postgres audit ledger
    -> optional marketplace reporting/export nodes
```

## Cross-Step Verification
Run these after the full sequence is implemented:

```bash
uv run pytest
uv run bpg doctor examples/wrappers/parse-sum-email/process.bpg.yaml
uv run bpg run sample-parse-sum-email --input examples/wrappers/parse-sum-email/input.yaml --engine local
uv run bpg replay <run-id> --json
```

Add Postgres and Temporal integration verification once those services are available in the local test environment.
