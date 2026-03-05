# CLI: bpg fmt

```yaml
doc_metadata:
  topic: cli_fmt
  version: 1
  summary: Canonicalize process YAML ordering and formatting.
```

## Summary
`bpg fmt` ensures process files follow a canonical key ordering and formatting style.

## When to use
Use before committing or applying changes to maintain consistent spec structure and reduce diff noise.

## Core idea
Deterministic formatting supports better diffing and more reliable automated repair by AI agents.

## Example
```bash
# Format in-place
uv run bpg fmt process.bpg.yaml

# Check if formatting is needed (CI mode)
uv run bpg fmt process.bpg.yaml --check

# Print formatted output to stdout without writing
uv run bpg fmt process.bpg.yaml --no-write
```

## Options
- `--check`: Return non-zero if the file is not canonical.
- `--write` / `--no-write`: Control whether to overwrite the input file (default: true).

## Related pages
- [CLI: bpg doctor](doctor.md)
- [Diff Minimality Patterns](../ai/prompt_patterns.md)
