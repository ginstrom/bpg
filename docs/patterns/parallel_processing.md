# Pattern: Parallel Processing

```yaml
doc_metadata:
  topic: pattern_parallel_processing
  version: 1
  summary: Fan-out/fan-in process design for independent tasks with deterministic merge behavior.
```

## Summary
Parallel branches improve throughput when tasks are independent and contract-aligned.

## When to use
Use for multi-source enrichment, independent checks, and bulk transformations.

## Core idea
Design explicit branch edges and explicit merge mappings; avoid implicit shared state.

## Example
```text
ingest -> [extract_a, extract_b, extract_c] -> merge -> validate
```

## Common mistakes
- Hidden merge assumptions on field names.
- Non-deterministic conflict resolution for simultaneous branches.

## Related pages
- [Edges Concept](../concepts/edges.md)
- [Execution Concept](../concepts/execution.md)
- [Pattern: AI Evaluation Pipeline](ai_evaluation_pipeline.md)
