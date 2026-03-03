# AI Guide: How Agents Should Use BPG

```yaml
doc_metadata:
  topic: ai_how_to_use
  version: 1
  summary: Operational playbook for agents to design, validate, and evolve BPG specs.
```

## Summary
Agents should treat BPG as a constrained process language with compiler-driven iteration.

## When to use
Use this for autonomous or human-in-the-loop agent workflows that author process specs.

## Core idea
Preferred loop:
1. Generate skeleton with explicit scaffold options.
2. Validate with `doctor`.
3. Apply targeted fixes.
4. Re-validate and format.
5. Plan/apply/run/replay.

## Example
```bash
uv run bpg init --name triage-claims --with-review --output process.bpg.yaml
uv run bpg doctor process.bpg.yaml --json
uv run bpg suggest-fix process.bpg.yaml --json
uv run bpg plan process.bpg.yaml --json --explain
```

## Common mistakes
- Producing free-form DSL variants instead of canonical shape.
- Ignoring provider metadata discovery before selecting providers.

## Related pages
- [AI Guide: Prompt Patterns](prompt_patterns.md)
- [AI Guide: Repair Strategies](repair_strategies.md)
- [Reference: Provider Interface](../reference/provider_interface.md)
