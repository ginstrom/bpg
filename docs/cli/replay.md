# CLI: bpg replay

```yaml
doc_metadata:
  topic: cli_replay
  version: 1
  summary: Reconstruct and inspect the full event history of a process run.
```

## Summary
`bpg replay` processes the append-only event log of a run to reconstruct the final state and detailed execution timeline.

## When to use
Use for auditing, deep debugging, and detailed analysis of process execution behavior.

## Core idea
Replaying events ensures that the reported run status is always derived from the source-of-truth log, making BPG execution histories fully auditable.

## Example
```bash
# Human-readable replay summary
uv run bpg replay <run-id>

# Machine-readable replay state (JSON)
uv run bpg replay <run-id> --json
```

## Options
- `run_id`: The identifier for the target run.
- `--json`: Emit a structured replay payload containing full state and logs.
- `--state-dir`: Directory where BPG state is persisted.

## Related pages
- [CLI: bpg status](status.md)
- [Execution Concept](../concepts/execution.md)
