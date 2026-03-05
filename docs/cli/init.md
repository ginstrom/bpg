# CLI: bpg init

```yaml
doc_metadata:
  topic: cli_init
  version: 1
  summary: Generate a process scaffold with explicit options or from intent.
```

## Summary
`bpg init` generates a new `process.bpg.yaml` scaffold to accelerate development.

## When to use
Use when starting a new process or adding common patterns (like human-in-the-loop review) to an existing project.

## Core idea
Scaffolding provides a correct structural starting point, reducing manual YAML entry errors.

## Example
```bash
# Basic scaffold
uv run bpg init --name my-process --output process.bpg.yaml

# Scaffold with human review node
uv run bpg init --name approval-flow --with-review --output process.bpg.yaml

# Scaffold with TODOs manifest for AI agents
uv run bpg init --name support-triage --todos-out todos.json
```

## Options
- `--name`: Set `metadata.name` in the generated file.
- `--description`: Set `metadata.description`.
- `--with-review` / `--with-hitl`: Include a `dashboard.form` review node and associated edges.
- `--output` / `-o`: Destination file path (default: `process.bpg.yaml`).
- `--todos-out`: Write a JSON manifest of missing configurations (e.g. provider selection).
- `--json`: Emit the scaffold and TODOs to stdout as JSON.

## Related pages
- [Build Process Guide](../guides/build_process.md)
- [Add Human Review Guide](../guides/add_human_review.md)
