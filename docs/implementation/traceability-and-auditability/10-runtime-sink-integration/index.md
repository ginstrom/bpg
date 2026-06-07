# 10. Runtime Sink Integration

## Objective
Wire configured tracing and audit sinks into production execution paths so canonical events emitted by `LangGraphRuntime` reach OpenTelemetry and Postgres during normal `bpg run` execution.

## Rationale
Steps 2–5 built `build_observability_sink()` and policy-aware Postgres/OTel sinks, but production backends currently instantiate `LangGraphRuntime` without an `event_sink`. Events are emitted and then discarded by `NoopEventSink`. This violates the design principle that mandatory audit capture lives in the runtime, not optional marketplace nodes.

## Primary Touchpoints
- `src/bpg/engines/langgraph/backend.py`
- `packages/bpg-temporal/src/bpg_temporal/runtime.py`
- `src/bpg/runtime/langgraph_runtime.py`
- `src/bpg/runtime/engine.py`
- `src/bpg/runtime/observability.py`
- `src/bpg/cli.py` (if `bpg run` has a separate execution entrypoint)
- `tests/test_langgraph_runtime.py`
- `tests/test_audit_postgres.py`
- `tests/test_observability.py`
- `tests/test_engine_backends.py`

## Scope

### In scope
- Build an observability sink from `process.observability` (tracing + audit config) at runtime startup.
- Pass the sink into `LangGraphRuntime(event_sink=...)`.
- Preserve existing `events.jsonl` replay behavior through `Engine` and `StateStore`.
- Ensure audit `failure_policy: fail_run` can abort a run when Postgres insert fails.
- Ensure tracing exporter failures remain non-fatal.
- Add an integration-style unit test that proves audit rows would be written when a fake/in-memory audit sink is wired through the backend path.

### Out of scope
- New sink types beyond Postgres and OTLP.
- Changing marketplace helper node behavior.
- Migrating legacy `policy.audit` retention/export fields to `observability.audit` (document coexistence only).

## Implementation Tasks

1. Add a small helper, for example `build_runtime_event_sink(process)`, that:
   - Reads `process.observability` when present.
   - Calls `build_observability_sink(...)`.
   - Falls back to `NoopEventSink` when observability is unset or fully disabled.

2. Update `LangGraphExecutionBackend.run()` to pass the configured sink into `LangGraphRuntime`.

3. Update `BpgWorkflow.run()` in `bpg_temporal/runtime.py` the same way.

4. Decide how `Engine` should interact with runtime sinks:
   - Preferred: backend-owned sink handles live emission; `Engine` continues writing `events.jsonl` from execution results.
   - Avoid double-inserting audit rows if both paths emit the same lifecycle transition.

5. Thread trace/span IDs from `OpenTelemetryEventSink` back onto emitted events before audit persistence when tracing is enabled (sink ordering already documents tracing before audit in `build_observability_sink`).

6. Add tests:
   - Backend path uses non-noop sink when audit is enabled.
   - `failure_policy: fail_run` propagates from sink to run failure.
   - Tracing setup failure does not fail the run.
   - Disabled audit (`failure_policy: disabled` or `enabled: false`) leaves only replay/logging behavior.

7. Update any example or fixture README that currently implies audit works without sink wiring.

## Acceptance Criteria
- `observability.audit.enabled: true` with a valid DSN causes runtime-emitted canonical events to reach `PostgresAuditEventSink` during `bpg run` through the LangGraph backend.
- Temporal backend path uses the same sink wiring.
- `observability.tracing.enabled: true` exports spans for the same run without failing execution.
- Local execution still works with observability unset.
- `events.jsonl` replay remains unchanged for runs without durable audit enabled.
- No duplicate audit rows are written for the same `event_id`.

## Verification

```bash
uv run pytest tests/test_langgraph_runtime.py tests/test_audit_postgres.py tests/test_observability.py tests/test_engine_backends.py -k "observability or audit or sink or runtime"
uv run bpg doctor tests/fixtures/audit_policy/enabled.bpg.yaml
```

With Postgres:

```bash
export BPG_AUDIT_DATABASE_URL=postgresql://bpg:bpg@localhost:55432/bpg
uv run bpg run <audit-enabled-process> --engine local
uv run bpg audit show <run-id>
uv run bpg audit verify <run-id>
```

## Dependencies
- Requires steps 2–5 from the original plan (already complete).
- Blocks meaningful end-to-end validation of steps 6–9 in production runs.

## Risks
- **Double emission**: `Engine` appends execution events to `events.jsonl` while runtime emits to sinks. Ensure only one path writes durable audit rows.
- **Legacy policy overlap**: `policy.audit` (retention/export tags) and `observability.audit` (durable sink) currently coexist. Document which controls durable capture.
