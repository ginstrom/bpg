# CLI: bpg plan

```yaml
doc_metadata:
  topic: cli_plan
  version: 1
  summary: Compile a process and show/apply-safe diff against deployed state.
```

## Summary
`bpg plan` validates a process and computes change impact before deployment.

## When to use
Use before every `apply` to review node/edge/schema and compatibility changes.

## Core idea
Planning is mandatory for safe evolution and explicit blast-radius review.

## Example
```bash
uv run bpg plan process.bpg.yaml --json --explain
uv run bpg plan process.bpg.yaml --out plan.out
uv run bpg show plan.out --json
```

## Common mistakes
- Running `apply` without inspecting plan output.
- Ignoring `compatibility_warnings` from `--explain` payload.

## Related pages
- [CLI: bpg apply](apply.md)
- [Versioning Concept](../concepts/versioning.md)
- [Modify Process Guide](../guides/modify_process.md)
