# Build Process Guide

```yaml
doc_metadata:
  topic: build_process
  version: 1
  summary: Step-by-step guide to build a process graph from intent.
```

## Summary
Build a process by defining types, node types, nodes, and explicit edges, then validate and deploy.

## When to use
Use this for greenfield process creation or when converting scripts into a managed graph.

## Core idea
Start constrained and explicit. Let compiler feedback drive correctness.

## Example
```bash
uv run bpg init --from-intent "process invoices with review" --output process.bpg.yaml --todos-out todos.json
uv run bpg doctor process.bpg.yaml --json
uv run bpg plan process.bpg.yaml --json --explain
uv run bpg apply process.bpg.yaml --auto-approve
```

## Common mistakes
- Writing a large spec before first validation.
- Skipping TODO completion from `init --from-intent` output.

## Related pages
- [Quickstart](../quickstart.md)
- [Modify Process Guide](modify_process.md)
- [How Agents Should Use BPG](../ai/how_agents_should_use_bpg.md)
