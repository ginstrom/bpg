# Versioning Concept

```yaml
doc_metadata:
  topic: versioning
  version: 1
  summary: Versioning protects compatibility across process, type, and node-type changes.
```

## Summary
BPG compares current and deployed state during planning and warns or blocks incompatible changes.

## When to use
Use versioning practices for any process change that could affect active runs or downstream consumers.

## Core idea
Promote safe evolution: bump versions intentionally, inspect plan diffs, and avoid breaking contracts silently.

## Example
```bash
uv run bpg plan process.bpg.yaml --json --explain
```

## Common mistakes
- Editing type contracts in-place without version discipline.
- Ignoring compatibility warnings in explain output.

## Related pages
- [Plan CLI](../cli/plan.md)
- [Modify Process Guide](../guides/modify_process.md)
- [Process Schema Reference](../reference/process_schema.md)
