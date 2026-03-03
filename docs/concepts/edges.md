# Edges Concept

```yaml
doc_metadata:
  topic: edges
  version: 1
  summary: Edges define explicit data mapping and conditional routing between nodes.
```

## Summary
Edges connect upstream node outputs to downstream node inputs with explicit field-level mappings.

## When to use
Use edges whenever a downstream node depends on upstream data or requires conditional branching.

## Core idea
No implicit field passing. `edge.with` is the canonical data-flow declaration.

## Example
```yaml
edges:
  - from: classify
    to: review
    when: classify.out.confidence < 0.8
    with:
      label: classify.out.label
      confidence: classify.out.confidence
```

## Common mistakes
- Omitting required target fields in `with` mappings.
- Using ambiguous expressions instead of explicit source paths.

## Related pages
- [Execution Concept](execution.md)
- [Edge Schema](../reference/edge_schema.md)
- [Validation Pattern](../patterns/validation_pattern.md)
