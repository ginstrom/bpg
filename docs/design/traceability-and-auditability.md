# Traceability and Auditability Design

```yaml
doc_metadata:
  topic: traceability_and_auditability
  version: 1
  summary: Design for OpenTelemetry tracing and tamper-evident audit records in BPG.
```

## Summary
BPG should implement traceability and auditability as separate runtime capabilities fed by one canonical event model.

Tracing is operational telemetry. BPG emits OpenTelemetry-compatible traces to configurable targets for debugging, latency analysis, dependency mapping, and backend correlation.

Audit is evidentiary record keeping. BPG writes append-only audit records to a Postgres-backed ledger with hash chaining, immutable database controls, redaction policy, and optional external anchoring.

Temporal contributes workflow metadata to both systems, but it is not the source of truth for either BPG tracing semantics or BPG audit semantics.

## Goals
- Provide end-to-end run and node traceability across BPG runtimes.
- Emit OpenTelemetry-compatible traces to standard OTLP collectors.
- Persist audit records in an append-only, tamper-evident ledger.
- Preserve BPG portability across Temporal, local, and future execution backends.
- Correlate traces, audit records, Temporal workflow history, provider calls, human approvals, and artifacts.
- Keep mandatory audit capture in the runtime, not in optional marketplace nodes.
- Support redaction and payload hashing before audit records leave the runtime.

## Non-Goals
- Do not use OpenTelemetry traces as compliance audit evidence.
- Do not use Temporal workflow history as the only audit ledger.
- Do not require users to add explicit audit nodes for core audit capture.
- Do not make Postgres cryptographically immutable by itself. Postgres is the ledger store; tamper evidence comes from hash chaining, update/delete prevention, and external anchoring.

## Core Decision
BPG owns a canonical runtime event envelope. The runtime emits events once, then routes them to specialized sinks:

```text
BPG runtime semantics
  -> canonical BPG event envelope
    -> OpenTelemetry trace exporter
    -> Postgres audit ledger
    -> local events.jsonl replay log
    -> optional marketplace reporting/export nodes

Temporal backend
  -> contributes workflow/activity/signal/timer metadata
  -> does not define the canonical event contract
```

## Event Model
The event model should converge the existing runtime observability events and SDK audit events into one internal envelope.

Required fields:

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

Conditional fields:

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

Important event types:

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

The event envelope should be stable enough for durable audit storage, while individual sinks can project it into sink-specific formats.

## Tracing Design
BPG should emit OpenTelemetry traces through a configurable tracing sink.

Span structure:

```text
trace = one BPG run
root span = process run
child span = each node execution
span events = retries, edge decisions, policy checks, HITL waits, artifact writes
span links = Temporal workflow/activity IDs, provider job IDs, child workflow IDs
```

Recommended span attributes:

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
bpg.audit.tags.*
bpg.temporal.namespace
bpg.temporal.workflow_id
bpg.temporal.run_id
bpg.temporal.activity_id
```

Configuration example:

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

Tracing should be treated as best-effort. Exporter failures must not affect workflow execution.

## Audit Design
Audit records should be written through a runtime-owned `AuditSink`. The first durable implementation should be a Postgres sink with append-only tables and per-run hash chains.

Audit table:

```sql
create table audit_events (
  sequence_id bigserial primary key,
  chain_scope text not null,
  chain_id text not null,
  event_id text not null unique,
  event_type text not null,
  occurred_at timestamptz not null,
  inserted_at timestamptz not null default now(),

  run_id text not null,
  process_name text not null,
  process_version text,
  process_hash text,
  node_id text,
  node_type text,

  actor_id text,
  actor_type text,
  policy_id text,
  correlation_id text,
  external_ref text,

  trace_id text,
  span_id text,

  payload jsonb not null,
  payload_sha256 text not null,
  previous_hash text,
  event_hash text not null
);
```

Recommended chain scope:

```text
chain_scope = run
chain_id = run_id
```

Start with per-run chains for straightforward concurrency and verification. Add periodic global checkpoints later to summarize many run chains.

Hash calculation:

```text
payload_sha256 = sha256(canonical_json(redacted_payload))

event_hash = sha256(canonical_json({
  previous_hash,
  chain_scope,
  chain_id,
  sequence_id,
  event_id,
  event_type,
  occurred_at,
  run_id,
  process_name,
  process_version,
  process_hash,
  node_id,
  node_type,
  actor_id,
  policy_id,
  correlation_id,
  external_ref,
  trace_id,
  span_id,
  payload_sha256
}))
```

The hash input must use canonical JSON serialization with deterministic key ordering and stable timestamp formatting.

## Immutability Controls
Postgres should enforce append-only behavior as defense in depth.

Recommended controls:

- Application role has `insert` and `select`, but no `update` or `delete`.
- Triggers reject `update` and `delete` on audit tables.
- Audit schema ownership is separate from the application runtime role.
- Row-level security can restrict reads if multi-tenant isolation is needed.
- Backups and WAL archiving are enabled.
- Chain heads are periodically anchored outside the database.

Trigger example:

```sql
create function prevent_audit_mutation()
returns trigger language plpgsql as $$
begin
  raise exception 'audit_events is append-only';
end;
$$;

create trigger audit_events_no_update
before update on audit_events
for each row execute function prevent_audit_mutation();

create trigger audit_events_no_delete
before delete on audit_events
for each row execute function prevent_audit_mutation();
```

## Chain Anchoring
Hash chaining inside one mutable database is tamper-evident only if verifiers have a trusted prior chain head. BPG should support checkpoint records and optional external anchoring.

Checkpoint table:

```sql
create table audit_chain_checkpoints (
  checkpoint_id bigserial primary key,
  created_at timestamptz not null default now(),
  scope text not null,
  last_sequence_id bigint not null,
  chain_head_hash text not null,
  anchored_ref text,
  signature text
);
```

Anchoring options:

- S3 Object Lock or equivalent write-once object storage.
- KMS-signed checkpoint files.
- Separately permissioned storage bucket.
- External transparency log.
- Manual export for regulated environments.

## Redaction and Payload Policy
Audit emission must apply redaction before durable storage.

Recommended behavior:

- Store redacted payload JSON by default.
- Store `payload_sha256` for the redacted payload.
- Store `input_sha256` and `output_sha256` for full payload correlation when full payloads are not retained.
- Record `redaction_policy_id` and redacted field paths.
- Allow process policy to opt into full payload retention only when explicitly configured.

Tracing should default to no raw input/output attributes. It may include payload hashes and sizes.

## Temporal Integration
Temporal should be integrated as a metadata provider and propagation boundary.

Temporal metadata to capture:

```text
namespace
workflow_id
workflow_run_id
activity_id
activity_type
attempt
task_queue
timer_id
signal_name
child_workflow_id
```

BPG should propagate trace context through Temporal workflow/activity boundaries where supported. Temporal workflow history remains useful corroborating evidence, but BPG audit records remain the compliance ledger.

## Marketplace Nodes
Marketplace nodes can compose audit-aware workflows, but must not be required for mandatory capture.

Appropriate marketplace nodes:

```text
export_audit_bundle
write_compliance_summary
notify_compliance_channel
create_audit_case
attach_evidence_to_ticket
verify_audit_chain
```

Inappropriate as the primary implementation:

```text
log_every_node_to_audit
record_approval_for_compliance
trace_workflow
```

Those responsibilities belong in the runtime because users could skip or bypass nodes.

## Implementation Plan
1. Define canonical BPG event envelope.
   Add a framework event model that can represent existing runtime events and audit events.

2. Refactor sinks around the canonical event.
   Keep local replay support, but make tracing and audit projections consume the same event envelope.

3. Implement OpenTelemetry tracing.
   Add an OTLP exporter sink, configuration parsing, span naming, attributes, trace context propagation, and tests with an in-memory exporter.

4. Implement Postgres audit sink.
   Add schema migration, append-only role guidance, canonical JSON hashing, per-run hash chaining, and verification helpers.

5. Add audit policy controls.
   Extend process policy with audit sink target, retention intent, payload retention, redaction behavior, and audit tags.

6. Wire Temporal metadata.
   Attach workflow, activity, signal, timer, and attempt metadata to canonical events from the Temporal runtime path.

7. Add checkpointing and anchoring.
   Implement checkpoint records first, then optional external anchoring providers.

8. Add CLI inspection and verification.
   Provide commands to show audit events, verify hash chains, export audit bundles, and print trace correlation IDs.

9. Add marketplace helper nodes.
   Add optional reporting/export/compliance nodes after runtime capture is stable.

## Verification Strategy
Unit tests:

- Canonical event schema validation.
- Deterministic canonical JSON serialization.
- Hash chain creation and verification.
- Redaction policy application.
- OpenTelemetry span projection.

Integration tests:

- Run a process and verify trace spans match run/node structure.
- Run a process and verify Postgres audit rows are append-only and hash chained.
- Verify update/delete trigger rejection.
- Verify replay from `events.jsonl` still works.
- Verify Temporal metadata is attached when using the Temporal backend.

Failure tests:

- Trace exporter failure does not fail the run.
- Audit sink failure follows configured policy.
- Hash chain verification fails after row mutation.
- Missing checkpoint anchor is reported as reduced assurance, not as proof of tampering.

## Open Questions
- Should audit sink failure fail the workflow by default in production, or should that be configurable per process?
- Should chains be per-run only at first, or should BPG also maintain a global chain from day one?
- Which external anchor should be first-party: S3 Object Lock, KMS-signed files, or a generic webhook?
- Should full payload retention be allowed globally, or only by explicit process policy with warnings?
- Should OpenTelemetry sampling ever be allowed for BPG traces, or should BPG default to always-on for workflow traces?

## Related Pages
- [Execution Concept](../concepts/execution.md)
- [Versioning Concept](../concepts/versioning.md)
- [Provider Interface](../reference/provider_interface.md)
