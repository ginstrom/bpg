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
