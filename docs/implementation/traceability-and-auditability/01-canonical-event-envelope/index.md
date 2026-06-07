# 1. Canonical Event Envelope

## Objective
Define a single internal BPG event envelope that can represent existing runtime observability events and SDK audit events.

## Rationale
Tracing, audit, replay, and reporting should consume one event contract. This prevents OpenTelemetry, Postgres audit, Temporal, and local replay from drifting into separate semantics.

## Primary Touchpoints
- `src/bpg/runtime/events.py`
- `src/bpg/runtime/observability.py`
- `packages/bpg-sdk/src/bpg_sdk/audit.py`
- Tests under `tests/` or the nearest existing runtime test package.

## Scope
Add a canonical event model with these required fields:

```text
schema_version
event_id
event_type
occurred_at
run_id
process_name
process_version
process_hash
engine_backend
```

Add optional fields from the design:

```text
node_id
node_type
node_package
trace_id
span_id
parent_span_id
correlation_id
causation_id
actor_id
actor_type
policy_id
external_ref
temporal_namespace
temporal_workflow_id
temporal_run_id
temporal_activity_id
provider_id
provider_job_id
artifact_name
artifact_sha256
input_sha256
output_sha256
redaction_policy_id
payload
payload_sha256
tags
```

Support these event types:

```text
run_started
run_completed
run_failed
node_scheduled
node_started
node_completed
node_failed
node_skipped
node_retry_scheduled
edge_fired
policy_checked
policy_blocked
approval_requested
approval_resolved
approval_timed_out
artifact_written
audit_checkpointed
```

## Implementation Tasks
1. Introduce a canonical event dataclass or Pydantic model.
2. Add validation for required fields and supported event types.
3. Add deterministic JSON serialization helpers for event payloads.
4. Add conversion helpers from existing `RunEvent` and SDK `AuditEvent` shapes.
5. Keep backward-compatible adapters for existing callers during the transition.

## Acceptance Criteria
- Runtime code can construct canonical events for run and node lifecycle events.
- Existing event replay behavior continues to work.
- Existing audit SDK event tests still pass or are updated to the canonical adapter.
- Unknown event types fail validation unless explicitly marked as extension events.
- Event serialization is deterministic across repeated runs with the same input.

## Verification
```bash
uv run pytest tests -k "event or observability or audit"
```

If the repo does not already have matching test names, add focused tests and run the exact files added in this step.

## Out of Scope
- OpenTelemetry exporters.
- Postgres persistence.
- Temporal metadata capture beyond reserving fields.
