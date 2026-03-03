# CLI: bpg apply

```yaml
doc_metadata:
  topic: cli_apply
  version: 1
  summary: Deploy validated process changes into BPG state.
```

## Summary
`bpg apply` persists process updates after validation and planning checks.

## When to use
Use after reviewing plan output and confirming compatibility.

## Core idea
Apply is the state transition point from desired spec to deployed spec.

## Example
```bash
uv run bpg apply process.bpg.yaml --auto-approve
```

## Common mistakes
- Treating apply as a runtime command.
- Applying from an unformatted or unvalidated spec.

## Related pages
- [CLI: bpg plan](plan.md)
- [Quickstart](../quickstart.md)
- [CLI: bpg run](run.md)
