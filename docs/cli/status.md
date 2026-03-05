# CLI: bpg status

```yaml
doc_metadata:
  topic: cli_status
  version: 1
  summary: Inspect the status of in-flight or completed process runs.
```

## Summary
`bpg status` provides visibility into the current state and execution history of one or more process runs.

## When to use
Use to monitor progress, identify failed steps, and check the overall status of runs in the BPG state store.

## Example
```bash
# List recent runs across all processes
uv run bpg status

# List recent runs for a specific process
uv run bpg status --process support-triage

# Show detailed status for a specific run ID
uv run bpg status <run-id>
```

## Options
- `run_id`: Optional identifier to inspect a single run.
- `--process`: Filter results by process name.
- `--state-dir`: Directory where BPG state is persisted (default: `.bpg-state`).

## Related pages
- [CLI: bpg run](run.md)
- [CLI: bpg replay](replay.md)
