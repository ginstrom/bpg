# Execution Concept

```yaml
doc_metadata:
  topic: execution
  version: 1
  summary: BPG runtime owns scheduling semantics and event-sourced run state.
```

## Summary
BPG execution is deterministic at the process semantics layer, with engine adapters used as pluggable node executors.

## When to use
Use this model when you need stable behavior across engine backends and auditable run histories.

## Core idea
BPG owns state transitions, eligibility, retries, and event schemas. Engines execute node work and report status.

## Run outputs and artifacts
- Final process output is persisted in run state (`run.yaml -> output`).
- Node outputs are persisted per node (`runs/<run_id>/nodes/*.yaml`).
- Declared process `artifacts` are written at completion under `runs/<run_id>/artifacts/` unless `artifacts[].path` overrides location.
- Artifact writes emit `artifact_written` events with `artifact_path`, `format`, `sha256`, and `bytes`.

## Example
```bash
uv run bpg run support_flow --input input.json --engine langgraph
uv run bpg run support_flow --input input.json --engine local
uv run bpg replay <run-id> --json
```

## Common mistakes
- Assuming backend selection changes process graph semantics.
- Treating engine-internal state as source of truth instead of BPG event logs.

## Related pages
- [Run CLI](../cli/run.md)
- [Plan CLI](../cli/plan.md)
- [Retry Pattern](../patterns/retry_pattern.md)
