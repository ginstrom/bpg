# AI Guide: Repair Strategies

```yaml
doc_metadata:
  topic: ai_repair_strategies
  version: 1
  summary: Deterministic strategies for converting diagnostics into minimal valid patches.
```

## Summary
Repair specs by mapping diagnostics to patch operations, then validating each patch incrementally.

## When to use
Use for autonomous error correction loops in editors, CI bots, and agent frameworks.

## Core idea
Patch minimally and locally; avoid whole-file rewrites.

## Example
```json
[
  {"op": "add", "path": "$.types", "value": {"RequiredType": {"ok": "bool"}}}
]
```

```bash
uv run bpg apply-patch process.bpg.yaml patch.json
uv run bpg doctor process.bpg.yaml --json
```

## Common mistakes
- Applying multiple speculative edits at once.
- Not normalizing and re-validating after each patch.

## Related pages
- [Reference: Error Codes](../reference/error_codes.md)
- [CLI: bpg doctor](../cli/doctor.md)
- [Pattern: Validation Loop](../patterns/validation_pattern.md)
