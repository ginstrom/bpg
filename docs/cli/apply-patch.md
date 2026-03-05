# CLI: bpg apply-patch

```yaml
doc_metadata:
  topic: cli_apply_patch
  version: 1
  summary: Apply JSON patch operations to a process spec.
```

## Summary
`bpg apply-patch` applies standard JSON patch operations to the process YAML definition using `$`-prefixed paths.

## When to use
Use for programmatic process modification, particularly by AI agents or automated scripts to fix specific validation errors or apply targeted updates.

## Example
```bash
# Apply a patch and save back to process.bpg.yaml
uv run bpg apply-patch process.bpg.yaml my-fix.json

# Preview patched output without writing
uv run bpg apply-patch process.bpg.yaml my-fix.json --no-in-place
```

## Options
- `process_file`: Path to the process YAML definition.
- `patch_file`: Path to the JSON patch file containing operations.
- `--in-place` / `--no-in-place`: Whether to write the patched spec back to the process file (default: true).

## Related pages
- [Repair Strategies](../ai/repair_strategies.md)
- [CLI: bpg suggest-fix](suggest-fix.md)
- [CLI: bpg fmt](fmt.md)
