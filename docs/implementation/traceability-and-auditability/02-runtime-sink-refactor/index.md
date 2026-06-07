# 2. Runtime Sink Refactor

## Objective
Route canonical BPG events through runtime-owned sinks while preserving local replay support.

## Rationale
Once the canonical event exists, sinks should project that event into local logs, traces, audit rows, or reporting outputs. Runtime code should not construct separate sink-specific event shapes for the same state transition.

## Primary Touchpoints
- `src/bpg/runtime/observability.py`
- `src/bpg/runtime/langgraph_runtime.py`
- `src/bpg/runtime/events.py`
- `src/bpg/state/store.py`
- `packages/bpg-sdk/src/bpg_sdk/audit.py`

## Scope
Create a sink interface that accepts canonical events. Keep existing `events.jsonl` replay log behavior intact.

Recommended interfaces:

```python
class EventSink(Protocol):
    def emit(self, event: BpgEvent) -> None: ...

class EventSinkGroup:
    def emit(self, event: BpgEvent) -> None: ...
```

Sink group behavior:

- Emit to all configured sinks.
- Preserve sink ordering for deterministic local behavior.
- Treat tracing sink failures as best-effort in a later step.
- Leave audit failure handling configurable in a later step.

## Implementation Tasks
1. Update local list/logging sinks to consume canonical events.
2. Add an adapter for legacy sink callers if needed.
3. Update runtime execution paths to emit canonical events at lifecycle boundaries.
4. Ensure local state writes continue to append replayable `events.jsonl` entries.
5. Add tests that compare replay state before and after the refactor.

## Acceptance Criteria
- Local run execution emits canonical events.
- `events.jsonl` remains readable by the existing replay path.
- Runtime code has one event emission path per lifecycle transition.
- Sink group tests cover multiple sinks and sink ordering.
- No tracing or Postgres dependency is required for local execution.

## Verification
```bash
uv run pytest tests -k "runtime or replay or observability"
uv run bpg run sample-parse-sum-email --input examples/wrappers/parse-sum-email/input.yaml --engine local
uv run bpg replay <run-id> --json
```

Replace `<run-id>` with the run ID printed by the local run.

## Out of Scope
- Audit hash chaining.
- OpenTelemetry span projection.
- New CLI audit commands.
