# CLI: bpg up

```yaml
doc_metadata:
  topic: cli_up
  version: 1
  summary: Start a local development runtime for a process.
```

## Summary
`bpg up` brings up a local runtime for testing and interacting with a process.

## When to use
Use during development and testing to run processes locally before deploying to shared environments.

## Core idea
Leverages Docker Compose to orchestrate local runtime services, providing an easy-to-use local testing environment.

## Example
```bash
# Basic local runtime
uv run bpg up process.bpg.yaml

# Local runtime with dashboard enabled
uv run bpg up process.bpg.yaml --dashboard --force
```

## Dashboard Access
If `--dashboard` is provided, the dashboard is typically available at `http://localhost:8080`.

## Options
- `--local-dir`: Directory for local runtime artifacts (default: `.bpg/local/<process_name>`).
- `--force`: Overwrite local runtime directory if it exists.
- `--dashboard`: Include and start the BPG dashboard.
- `--dashboard-port`: Port for dashboard (default: 8080).
- `--providers-file`: Custom provider registry.

## Related pages
- [CLI: bpg down](down.md)
- [CLI: bpg logs](logs.md)
- [Quickstart](../quickstart.md)
