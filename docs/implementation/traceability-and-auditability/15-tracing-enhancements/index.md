# 15. Tracing Enhancements

## Objective
Close remaining gaps between the tracing design and the current OpenTelemetry sink implementation.

## Rationale
The tracing sink projects canonical events into run and node spans with rich attributes and span events. The design also calls for span links across Temporal, provider, and child-workflow boundaries, plus trace-context propagation through Temporal workflow/activity boundaries. These are not yet implemented.

## Primary Touchpoints
- `src/bpg/runtime/observability.py`
- `packages/bpg-temporal/src/bpg_temporal/runtime.py`
- `packages/bpg-temporal/src/bpg_temporal/metadata.py`
- `tests/test_observability.py`
- `tests/test_temporal_metadata.py`

## Scope

### In scope
- Add span links when canonical events carry:
  - `temporal_workflow_id` / `temporal_activity_id`
  - `provider_job_id`
  - `temporal_child_workflow_id`
- Propagate OpenTelemetry trace context through Temporal workflow/activity boundaries where the Temporal SDK supports it.
- Align attribute naming with design where low-risk:
  - Consider `bpg.audit.tags.*` aliases alongside existing `bpg.tag.*` attributes, or document intentional divergence.
- Add in-memory exporter tests for links and propagated context.

### Out of scope
- Changing audit ledger behavior.
- Sampling strategy debates beyond current `always` / `never` support.
- Raw input/output emission defaults (remain opt-in).

## Implementation Tasks

1. Evaluate Temporal Python SDK support for context propagation (`traceparent` injection/extraction on workflow/activity payloads or headers).

2. Add a small propagation helper used by Temporal runtime entry/exit points.

3. Extend `OpenTelemetryEventSink` to create `SpanLink` entries when link target identifiers are present on events.

4. Add tests:
   - Link creation for Temporal and provider identifiers.
   - Propagated trace ID remains stable across a mocked boundary crossing.
   - Exporter failure remains non-fatal.

5. Document any Temporal SDK limitations that prevent full propagation.

## Acceptance Criteria
- Temporal-backed runs preserve trace correlation across at least one workflow/activity boundary in tests.
- Span links are emitted for configured identifier fields without breaking existing span structure.
- Existing tracing tests continue to pass.
- Tracing remains disabled by default unless `observability.tracing.enabled: true`.

## Verification

```bash
uv run pytest tests/test_observability.py tests/test_temporal_metadata.py -k "opentelemetry or tracing or propagat or link"
```

## Dependencies
- Should follow [10. Runtime Sink Integration](10-runtime-sink-integration/index.md) so enhancements are exercised in real runs.
- Lower priority than audit completeness workstreams.
