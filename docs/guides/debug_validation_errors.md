# Debug Validation Errors Guide

```yaml
doc_metadata:
  topic: debug_validation_errors
  version: 1
  summary: Use machine-readable diagnostics and patch suggestions to repair invalid specs.
```

## Summary
BPG diagnostics include stable codes, paths, and fix hints that support fast human or agent repair loops.

## When to use
Use this when `bpg doctor` or `bpg plan --json-errors` reports validation failures.

## Core idea
Repair iteratively using diagnostics and patch suggestions, not manual guesswork.

## Example
```bash
uv run bpg doctor process.bpg.yaml --json
uv run bpg suggest-fix process.bpg.yaml --json > suggestions.json
uv run bpg apply-patch process.bpg.yaml patch.json
uv run bpg doctor process.bpg.yaml --json
```

## Common mistakes
- Ignoring error `path` and editing unrelated sections.
- Applying patch suggestions without re-validating.

## Related pages
- [Error Codes Reference](../reference/error_codes.md)
- [Doctor CLI](../cli/doctor.md)
- [Repair Strategies](../ai/repair_strategies.md)
