# Add AI Step Guide

```yaml
doc_metadata:
  topic: add_ai_step
  version: 1
  summary: Add an AI node with typed outputs and conditional routing.
```

## Summary
Insert an AI step as a node type + node instance, then wire explicit edge mappings.

## When to use
Use when adding classification, extraction, scoring, or evaluation tasks.

## Core idea
AI steps are regular nodes. Reliability comes from strict output schemas and downstream validation.

## Example
```yaml
node_types:
  classify@v1:
    in: DocIn
    out: ClassifyOut
    provider: mock
    version: v1
    config_schema: {}

nodes:
  classify:
    type: classify@v1
    config: {}

edges:
  - from: input
    to: classify
    with:
      text: input.out.text
```

## Common mistakes
- Leaving AI outputs untyped or too loose for downstream use.
- Coupling retries/branching inside provider logic.

## Related pages
- [Nodes Concept](../concepts/nodes.md)
- [Provider Interface Reference](../reference/provider_interface.md)
- [AI Evaluation Pipeline Pattern](../patterns/ai_evaluation_pipeline.md)
