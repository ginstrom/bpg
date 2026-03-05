# CLI: bpg logs

```yaml
doc_metadata:
  topic: cli_logs
  version: 1
  summary: Stream logs from local runtime services.
```

## Summary
`bpg logs` streams terminal output from services running in a local runtime.

## When to use
Use during local development and testing to monitor process execution and debug provider-level issues.

## Example
```bash
# Stream all logs from default runtime
uv run bpg logs

# Stream logs for a specific service (e.g. bpg-runtime)
uv run bpg logs --service bpg-runtime

# Stream logs from a specific runtime directory
uv run bpg logs --local-dir .bpg/local/my-process
```

## Options
- `--local-dir`: Directory for local runtime artifacts.
- `--service`: Filter logs for a specific service name.

## Related pages
- [CLI: bpg up](up.md)
- [CLI: bpg down](down.md)
