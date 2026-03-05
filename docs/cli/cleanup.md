# CLI: bpg cleanup

```yaml
doc_metadata:
  topic: cli_cleanup
  version: 1
  summary: Prune old run records from local state store.
```

## Summary
`bpg cleanup` removes historical run data from the BPG state directory to save space and maintain performance.

## When to use
Use regularly in local development or CI environments to purge obsolete run logs and state artifacts.

## Example
```bash
# Preview cleanup without deleting data
uv run bpg cleanup --dry-run

# Delete runs older than 30 days
uv run bpg cleanup --older-than 30d

# Delete only failed runs older than 1 week
uv run bpg cleanup --status failed --older-than 7d
```

## Options
- `--older-than`: Duration literal (e.g. `30d`, `12h`, `5m`) specifying the age of runs to delete.
- `--status`: Comma-separated list of run statuses to target (e.g. `completed,failed`).
- `--process`: Filter by process name.
- `--dry-run`: Show what would be deleted without performing actual removals.
- `--state-dir`: Directory for BPG state storage.

## Related pages
- [CLI: bpg status](status.md)
- [CLI: bpg replay](replay.md)
