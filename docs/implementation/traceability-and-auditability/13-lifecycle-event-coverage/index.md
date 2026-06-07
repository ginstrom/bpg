# 13. Lifecycle Event Coverage

## Objective
Emit the remaining canonical event types from runtime execution paths so the event contract matches the design and audit ledger completely describes run behavior.

## Rationale
`BpgEvent` defines 17 core event types, but production runtime paths currently emit only a subset. Missing categories include scheduling, edge decisions, policy blocks, and human-approval lifecycle transitions. The schema and replay adapters already support these types; runtime emission is incomplete.

## Primary Touchpoints
- `src/bpg/runtime/langgraph_runtime.py`
- `src/bpg/runtime/orchestrator.py`
- `src/bpg/runtime/engine.py`
- `packages/bpg-temporal/src/bpg_temporal/hitl.py`
- `src/bpg/runtime/events.py`
- `src/bpg/runtime/observability.py` (span event mapping)
- `tests/test_langgraph_runtime.py`
- `tests/test_observability.py`
- `tests/test_slack_interactive.py` (approval flows, if applicable)

## Scope

### Target event types

| Event type | Intended source |
|------------|-----------------|
| `node_scheduled` | Node becomes eligible before execution starts |
| `edge_fired` | Outgoing edge selected / branch taken |
| `policy_blocked` | Policy denies execution |
| `approval_requested` | HITL wait begins |
| `approval_resolved` | HITL signal received (approved/rejected/escalated) |
| `approval_timed_out` | HITL timeout expires |

### Already emitted (keep stable)
- `run_started`, `run_completed`, `run_failed`
- `node_started`, `node_completed`, `node_failed`, `node_skipped`, `node_retry_scheduled`
- `policy_checked`
- `artifact_written` (Engine/state-store path)
- `audit_checkpointed` (checkpoint API)

### Out of scope
- New event types beyond the canonical contract.
- Changing legacy alias behavior in `LEGACY_EVENT_TYPE_ALIASES`.

## Implementation Tasks

1. Audit each runtime transition and map it to a canonical `event_type`.

2. Emit `node_scheduled` when a node becomes runnable and before `node_started`.

3. Emit `edge_fired` when the runtime chooses a branch/edge, including conditional edges and failure routes.

4. Emit `policy_blocked` when a policy rejects execution; keep `policy_checked` for allow/path decisions.

5. Wire approval lifecycle events:
   - `approval_requested` when entering a wait state.
   - `approval_resolved` on signal receipt (approved/rejected/escalated map through existing aliases).
   - `approval_timed_out` on timer expiry.
   - Include Temporal signal/timer metadata when available.

6. Ensure OpenTelemetry sink attaches these as span events on the correct node/run span.

7. Add focused tests per event family:
   - Scheduling before start.
   - Edge selection on branching process fixture.
   - Approval interrupt/resume fixture.
   - Policy block fixture.

8. Update any comments/tests that currently state `node_scheduled` is internal-only and not surfaced.

## Acceptance Criteria
- Each target event type is emitted at least once in a representative test fixture.
- Emitted events flow through configured sinks when [10. Runtime Sink Integration](10-runtime-sink-integration/index.md) is complete.
- `events.jsonl` and replay adapters remain backward compatible.
- OpenTelemetry span events include retries, edge decisions, policy checks, HITL waits, and artifact writes per design.

## Verification

```bash
uv run pytest tests/test_langgraph_runtime.py tests/test_observability.py tests/test_slack_interactive.py -k "event or approval or edge or policy or scheduled"
uv run bpg replay <run-id> --json
```

## Dependencies
- Can proceed in parallel with workstream 10.
- Approval events depend on existing HITL/Temporal wait-state behavior.
