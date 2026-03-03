# AI Guide: Prompt Patterns

```yaml
doc_metadata:
  topic: ai_prompt_patterns
  version: 1
  summary: Prompt templates that improve first-pass validity of generated BPG specs.
```

## Summary
Prompt for explicit tasks, typed contracts, and edge mappings to reduce repair iterations.

## When to use
Use when generating new specs or requesting targeted graph edits.

## Core idea
High-quality prompts require explicit constraints and output format requirements.

## Example
```text
Generate a canonical BPG YAML process for support triage.
Constraints:
- include metadata, types, node_types, nodes, trigger, edges
- explicit edge.with mappings for all required fields
- include one human review branch when confidence < 0.8
- no shorthand or implicit data passing
```

## Common mistakes
- Open-ended prompts without output shape constraints.
- Asking for runtime semantics in prose but not encoded in edges.

## Related pages
- [AI Guide: How Agents Should Use BPG](how_agents_should_use_bpg.md)
- [Guide: Build Process](../guides/build_process.md)
- [Reference: Process Schema](../reference/process_schema.md)
