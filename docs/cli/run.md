# CLI: bpg run

```yaml
doc_metadata:
  topic: cli_run
  version: 1
  summary: Trigger process execution with explicit backend selection and typed input payloads.
```

## Summary
`bpg run` starts a run for a deployed process and records event/state history in BPG state.

## When to use
Use to execute deployed specs and compare backend behavior (`langgraph`, `local`).

## Core idea
Execution backend is pluggable; BPG semantics and audit events remain canonical.

When a process declares `artifacts`, `bpg run` also materializes output files and appends `artifact_written` events with artifact locations.

## Example
```bash
uv run bpg run support_flow --input input.json --engine langgraph
uv run bpg run support_flow --input input.json --engine local
uv run bpg replay <run-id> --json
```

## Common mistakes
- Expecting backend-specific behavior changes in graph routing semantics.
- Running undeployed process names.

## Related pages
- [Execution Concept](../concepts/execution.md)
- [CLI: bpg plan](plan.md)
- [CLI: bpg apply](apply.md)
