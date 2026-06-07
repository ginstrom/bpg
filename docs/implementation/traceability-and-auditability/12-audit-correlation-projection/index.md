# 12. Audit Correlation Projection

## Objective
Ensure durable audit rows retain Temporal identifiers and payload correlation hashes that already exist on canonical `BpgEvent` instances.

## Rationale
`build_audit_record()` persists a fixed set of top-level columns plus a policy-projected `payload`. Temporal metadata and `input_sha256` / `output_sha256` live on `BpgEvent` but are often absent from stored audit payloads. CLI export helpers such as `extract_temporal_ids()` currently search payload keys, so bundles may miss Temporal correlation even when events carried it at emission time.

## Primary Touchpoints
- `src/bpg/audit/postgres.py` (`build_audit_record`, `audit_payload_for_event` usage)
- `src/bpg/audit/policy.py`
- `src/bpg/audit/inspection.py` (`extract_temporal_ids`, export bundle builder)
- `tests/test_audit_postgres.py`
- `tests/test_cli_audit.py`
- `tests/test_temporal_metadata.py`

## Scope

### In scope
- Project these canonical fields into durable audit storage:
  - All `temporal_*` event fields from `TEMPORAL_EVENT_FIELDS`
  - `input_sha256`, `output_sha256`
  - `redaction_policy_id`, `redacted_field_paths` (when not already present)
  - `tags` from the event envelope
- Keep the existing `audit_events` table schema unless a migration is clearly justified. Prefer enriching `payload` with a stable `_correlation` or `_event_context` section rather than adding many new columns immediately.
- Update export and CLI summary helpers to read projected correlation data.
- Add tests for Temporal-enriched events round-tripping into audit rows and export bundles.

### Out of scope
- New Postgres columns for every optional envelope field.
- Changing hash formula inputs unless required for verification consistency (document if deferred).

## Recommended Payload Shape

```json
{
  "_audit": {
    "payload_retention": "redacted",
    "payload_sha256": "...",
    "redaction_policy_id": "default",
    "redacted_field_paths": []
  },
  "_correlation": {
    "temporal_namespace": "default",
    "temporal_workflow_id": "wf-1",
    "temporal_activity_id": "act-1",
    "input_sha256": "...",
    "output_sha256": "...",
    "tags": {"environment": "production"}
  },
  "event_payload": {}
}
```

## Implementation Tasks

1. Add a helper to extract correlation fields from `BpgEvent`.

2. Merge correlation fields into the payload produced by `audit_payload_for_event()` or immediately before insert in `build_audit_record()`.

3. Update `extract_temporal_ids()` to read from `_correlation` first, with backward-compatible fallback to top-level payload keys.

4. Extend `bpg audit export` bundle tests to include Temporal and hash fields when present on source events.

5. Add a test that builds an audit record from a Temporal-enriched `BpgEvent` and asserts export helpers surface the identifiers.

## Acceptance Criteria
- Temporal-backed canonical events persist Temporal identifiers in audit payloads.
- `input_sha256` and `output_sha256` are present in audit payloads when set on the source event.
- `bpg audit export` and `extract_temporal_ids()` return Temporal IDs without custom payload shaping by callers.
- Existing audit verification and hash chain behavior remain correct.

## Verification

```bash
uv run pytest tests/test_audit_postgres.py tests/test_cli_audit.py tests/test_temporal_metadata.py -k "audit or temporal or export or correlation"
uv run bpg audit export <run-id> --output /tmp/bpg-audit-bundle.json
```

## Dependencies
- Best validated after [10. Runtime Sink Integration](10-runtime-sink-integration/index.md), but unit tests can proceed earlier.
