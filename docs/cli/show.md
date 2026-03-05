# CLI: bpg show

```yaml
doc_metadata:
  topic: cli_show
  version: 1
  summary: Inspect and summarize a saved BPG plan artifact.
```

## Summary
`bpg show` provides a human-readable or machine-readable inspection of a plan artifact produced by `bpg plan --out`.

## When to use
Use during deployment reviews and CI/CD pipelines to inspect exactly what changes are proposed in a specific plan artifact.

## Example
```bash
# Human-readable summary
uv run bpg show plan.out

# Machine-readable plan (JSON)
uv run bpg show plan.out --json
```

## Options
- `plan_file`: The plan artifact JSON file to inspect.
- `--json`: Emit raw plan JSON (similar to `terraform show -json`).

## Related pages
- [CLI: bpg plan](plan.md)
- [CLI: bpg apply](apply.md)
