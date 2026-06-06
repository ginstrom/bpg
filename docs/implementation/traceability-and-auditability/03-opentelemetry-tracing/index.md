# 3. OpenTelemetry Tracing

## Objective
Add a configurable OpenTelemetry tracing sink that projects canonical BPG events into traces and spans.

## Rationale
Tracing is operational telemetry. It should help debug latency, retries, policy checks, HITL waits, provider calls, Temporal correlation, and artifacts without becoming the compliance ledger.

## Primary Touchpoints
- Runtime configuration loading.
- `src/bpg/runtime/observability.py`
- `src/bpg/runtime/events.py`
- `pyproject.toml`
- Tests under runtime observability.

## Scope
Implement tracing configuration:

```yaml
observability:
  tracing:
    enabled: true
    exporter: otlp
    endpoint: http://localhost:4317
    protocol: grpc
    sample: always
    emit_input: false
    emit_output: false
```

Map events to span structure:

```text
trace = one BPG run
root span = process run
child span = each node execution
span events = retries, edge decisions, policy checks, HITL waits, artifact writes
span links = Temporal workflow/activity IDs, provider job IDs, child workflow IDs
```

Use span attributes from the design, including:

```text
bpg.run_id
bpg.process_name
bpg.process_version
bpg.process_hash
bpg.node_id
bpg.node_type
bpg.node_package
bpg.engine
bpg.provider_id
bpg.retry.attempt
bpg.policy.id
bpg.policy.result
bpg.audit.event_id
bpg.temporal.namespace
bpg.temporal.workflow_id
bpg.temporal.run_id
bpg.temporal.activity_id
```

## Implementation Tasks
1. Add OpenTelemetry dependencies with `uv`.
2. Implement an `OpenTelemetryEventSink`.
3. Maintain run and node span state from canonical events.
4. Emit span events for retries, edges, policy checks, approvals, and artifacts.
5. Add trace IDs and span IDs back onto canonical events when available.
6. Make exporter failures non-fatal.
7. Add in-memory exporter tests for span names, attributes, and status.

## Acceptance Criteria
- Tracing is disabled by default unless configuration enables it.
- Enabled tracing can export through OTLP.
- Local test exporter receives one trace per BPG run.
- Node lifecycle events produce child spans.
- Raw inputs and outputs are not emitted unless explicitly configured.
- Exporter failure does not fail workflow execution.

## Verification
```bash
uv run pytest tests -k "opentelemetry or tracing or observability"
uv run bpg run sample-parse-sum-email --input examples/wrappers/parse-sum-email/input.yaml --engine local
```

If an OTLP collector fixture is added, include one integration test that verifies spans arrive at the collector.

## Out of Scope
- Audit persistence.
- Audit failure policy.
- External checkpoint anchoring.
