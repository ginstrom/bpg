# OpenTelemetry Tracing Operations

```yaml
doc_metadata:
  topic: operations_tracing
  version: 1
  summary: Minimal operator guidance for OpenTelemetry tracing with BPG.
```

## Overview

BPG projects canonical runtime events into OpenTelemetry traces when
`observability.tracing.enabled` is true. Tracing is best-effort: export failures do not
fail the run unless paired with a strict audit `failure_policy`.

Traces are operational signals. The Postgres audit ledger remains the compliance
evidence store.

## Process configuration

```yaml
observability:
  tracing:
    enabled: true
    exporter: otlp
    endpoint: http://localhost:4318/v1/traces
    protocol: http/protobuf
    service_name: bpg-runtime
    sample: always
```

Defaults:

- Tracing is disabled unless `enabled: true`.
- Raw input/output span attributes remain off unless `emit_input` or `emit_output` is set.

## Collector setup

Point BPG at a local or managed OTLP endpoint. For a local collector, see the
[OpenTelemetry Collector documentation](https://opentelemetry.io/docs/collector/).

For local development with Kind, `k8s/kind-config.yaml` exposes OTLP ports 4317/4318 and
Jaeger UI on port 16686:

```bash
kind create cluster --config k8s/kind-config.yaml
```

Example environment override:

```bash
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```

Optional integration verification:

```bash
export BPG_TEST_OTEL_ENDPOINT=http://localhost:4318/v1/traces
uv run pytest -m integration -k otel
```

## Temporal boundary propagation

Temporal workflows can carry W3C trace context in the `_trace_context` payload field.
`BpgWorkflow` extracts the carrier and attaches it as the parent context for run spans.

Inject before starting a child workflow or activity:

```python
from bpg_temporal import inject_trace_context

carrier: dict[str, str] = {}
inject_trace_context(carrier)
payload = {"_trace_context": carrier, **business_input}
```

Span links are emitted when canonical events carry Temporal identifiers, provider job IDs,
or child workflow IDs.

## Correlation with audit rows

When tracing and audit are both enabled, the OpenTelemetry sink enriches canonical events
with `trace_id` and `span_id` before the audit sink persists them. Use
`bpg trace show <run-id>` to correlate audit rows with exported spans.

## Troubleshooting

**No spans in the collector**

- Confirm `observability.tracing.enabled: true` on the process.
- Verify network reachability to the OTLP endpoint.
- Check runtime logs for `OpenTelemetry event export failed`.

**Trace ID missing in audit rows**

- Audit and tracing must both be enabled on the same process.
- Tracing runs before audit in the runtime sink group; custom sink ordering may drop
  enrichment.

## Related pages

- [CLI: bpg trace](../cli/trace.md)
- [Audit ledger operations](audit-ledger.md)
- [Process schema: observability](../reference/process_schema.md)
