# CLI: bpg package

```yaml
doc_metadata:
  topic: cli_package
  version: 1
  summary: Generate a docker-compose bundle for process deployment.
```

## Summary
`bpg package` creates a standalone deployment artifact (Docker Compose) for a process.

## When to use
Use when preparing a process for production deployment or shared runtime environments.

## Core idea
Inference-based packaging automatically includes required internal services (ledger, dashboard) and generates necessary environment variables and configuration files.

## Example
```bash
# Basic package
uv run bpg package process.bpg.yaml --output-dir dist/my-package

# Package with dashboard included
uv run bpg package process.bpg.yaml --output-dir dist/package --dashboard

# Package using an explicit registry image
uv run bpg package process.bpg.yaml --output-dir dist/package --image ghcr.io/org/bpg:v1.2.0
```

## Generated Artifacts
The following files are written to the output directory:
- `docker-compose.yml`: Runtime orchestration.
- `.env.example` / `.env`: Configuration templates.
- `process.bpg.yaml`: Canonical spec.
- `package-metadata.json`: Integrity and versioning data.
- `Dockerfile` / `pyproject.toml` (if using local build mode).

## Options
- `--output-dir` / `-o`: Destination for artifacts.
- `--force`: Overwrite output directory if it exists.
- `--dashboard`: Include and configure the BPG dashboard service.
- `--dashboard-port`: Port for dashboard (default: 8080).
- `--image`: Explicit container image for the BPG runtime.
- `--providers-file`: Custom provider registry.

## Related pages
- [CLI: bpg up](up.md)
- [System Integration Tests](../guides/system_integration_tests.md)
