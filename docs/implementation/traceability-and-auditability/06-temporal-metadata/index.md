# 6. Temporal Metadata

## Objective
Attach Temporal workflow, activity, signal, timer, and attempt metadata to canonical BPG events emitted from the Temporal runtime path.

## Rationale
Temporal history is useful corroborating evidence, but BPG audit and tracing semantics remain portable. Temporal metadata should enrich canonical events without becoming the event contract.

## Primary Touchpoints
- `packages/bpg-temporal/src/bpg_temporal/runtime.py`
- `packages/bpg-temporal/src/bpg_temporal/backend.py`
- `packages/bpg-temporal/src/bpg_temporal/hitl.py`
- Runtime event emission adapters.
- Temporal package tests.

## Scope
Capture these fields when available:

```text
temporal_namespace
temporal_workflow_id
temporal_run_id
temporal_activity_id
activity_type
attempt
task_queue
timer_id
signal_name
child_workflow_id
```

Propagate OpenTelemetry trace context through Temporal workflow and activity boundaries where supported by the Temporal SDK.

## Implementation Tasks
1. Add a Temporal metadata extraction helper.
2. Attach workflow metadata to run lifecycle events.
3. Attach activity metadata to node lifecycle events.
4. Attach signal and timer metadata to HITL and wait events.
5. Add span links or attributes for Temporal identifiers in the tracing sink.
6. Add audit fields for Temporal identifiers in the Postgres projection where columns exist, or include them in payload otherwise.
7. Add tests using Temporal SDK test facilities or mocked Temporal context.

## Acceptance Criteria
- Temporal-backed runs emit canonical events with workflow IDs.
- Temporal-backed node executions emit activity IDs and attempt numbers when available.
- HITL signal events carry signal metadata when available.
- Trace spans include Temporal correlation attributes.
- Audit records retain Temporal correlation data.
- Local runtime behavior is unchanged.

## Verification
```bash
uv run pytest packages/bpg-temporal tests -k "temporal or tracing or audit"
```

If full Temporal integration tests are not available locally, add mocked context unit tests and document the missing integration coverage.

Current coverage uses mocked Temporal workflow/activity context and the existing
`bpg-temporal` bridge runtime. A live Temporal worker integration test should be
added once the repository has a local Temporal test service fixture.

## Out of Scope
- Making Temporal history the audit ledger.
- Adding Temporal-specific event types to the canonical contract unless they map to BPG semantics.
- Marketplace helper nodes.
