# Modify Process Guide

```yaml
doc_metadata:
  topic: modify_process
  version: 1
  summary: Make safe incremental process changes with plan/apply and replay checks.
```

## Summary
Use plan artifacts and compatibility warnings to evolve processes without hidden regressions.

## When to use
Use when adding nodes/edges, changing mappings, or introducing new types/providers.

## Core idea
Treat edits as small patches: change, validate, plan, apply, and verify replayed outcomes.

## Example
```bash
uv run bpg fmt process.bpg.yaml --check
uv run bpg doctor process.bpg.yaml --json
uv run bpg plan process.bpg.yaml --json --explain
uv run bpg apply process.bpg.yaml --auto-approve
```

## Common mistakes
- Large rewrites instead of localized graph edits.
- Applying without checking blast radius in explain output.

## Related pages
- [Versioning Concept](../concepts/versioning.md)
- [Plan CLI](../cli/plan.md)
- [Repair Strategies](../ai/repair_strategies.md)
