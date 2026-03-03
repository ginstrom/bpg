# Pattern: Validation Loop

```yaml
doc_metadata:
  topic: pattern_validation_loop
  version: 1
  summary: Use compile diagnostics + targeted patches to iterate toward valid specs.
```

## Summary
The validation loop is the default development cycle for AI and human authors.

## When to use
Use for new process generation, iterative editing, and CI policy enforcement.

## Core idea
Generate, validate, repair, and repeat until `doctor` is clean.

## Example
```text
generate spec -> doctor --json -> suggest-fix -> apply-patch -> doctor --json
```

## Common mistakes
- Running full runtime tests before clearing compile diagnostics.
- Manual edits that ignore structured patch suggestions.

## Related pages
- [CLI: bpg doctor](../cli/doctor.md)
- [Debug Validation Errors Guide](../guides/debug_validation_errors.md)
- [AI Repair Strategies](../ai/repair_strategies.md)
