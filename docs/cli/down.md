# CLI: bpg down

```yaml
doc_metadata:
  topic: cli_down
  version: 1
  summary: Tear down local runtime services.
```

## Summary
`bpg down` stops and removes local runtime containers and networks.

## When to use
Use when you are finished testing a process locally and want to free up system resources.

## Example
```bash
# Tear down default local runtime
uv run bpg down process.bpg.yaml

# Tear down local runtime from a specific directory
uv run bpg down --local-dir .bpg/local/custom
```

## Options
- `--local-dir`: Directory containing the runtime's Docker Compose artifacts.

## Related pages
- [CLI: bpg up](up.md)
- [CLI: bpg logs](logs.md)
