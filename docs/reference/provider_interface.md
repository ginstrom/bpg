# Provider Interface Reference

```yaml
doc_metadata:
  topic: provider_interface
  version: 1
  summary: Providers expose metadata and typed execution behavior discoverable through CLI.
```

## Summary
Providers are execution implementations bound to node types and surfaced through `bpg providers` metadata APIs.

## When to use
Use when selecting providers, building provider registries, or validating capabilities for agents.

## Core idea
Provider selection should be metadata-driven: schema, side effects, idempotency, and latency class.

## Example
```bash
uv run bpg providers list --json
uv run bpg providers describe mock --json
```

```json
{
  "name": "mock",
  "description": "Deterministic canned outputs for tests.",
  "input_schema": {"type": "object"},
  "output_schema": {"type": "object"},
  "side_effects": "none",
  "idempotency": "yes",
  "latency_class": "low",
  "examples": [{"title": "default", "config": {}, "input": {}}]
}
```

## Common mistakes
- Picking providers from memory instead of metadata inspection.
- Ignoring side effects/idempotency when designing retries.

## Related pages
- [How Agents Should Use BPG](../ai/how_agents_should_use_bpg.md)
- [Plan CLI](../cli/plan.md)
- [Add AI Step Guide](../guides/add_ai_step.md)
