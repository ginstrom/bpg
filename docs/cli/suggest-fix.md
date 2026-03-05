# CLI: bpg suggest-fix

```yaml
doc_metadata:
  topic: cli_suggest_fix
  version: 1
  summary: Generate JSON patch repairs from process diagnostics.
```

## Summary
`bpg suggest-fix` analyzes validation diagnostics and generates JSON patch operations that can fix common errors.

## When to use
Use during iterative development, especially in AI agent repair loops, to automatically generate fixes for reported `doctor` or `plan` errors.

## Example
```bash
# Generate suggestions and show them
uv run bpg suggest-fix process.bpg.yaml

# Generate suggestions as machine-readable JSON
uv run bpg suggest-fix process.bpg.yaml --json
```

## Options
- `process_file`: Path to the process YAML definition.
- `--json`: Emit suggestions including error codes and full patch operations.
- `--providers-file`: Custom provider registry for diagnostic context.

## Related pages
- [CLI: bpg doctor](doctor.md)
- [CLI: bpg apply-patch](apply-patch.md)
- [Repair Strategies](../ai/repair_strategies.md)
