# Nodes Concept

```yaml
doc_metadata:
  topic: nodes
  version: 1
  summary: Nodes are executable tasks bound to typed node types and providers.
```

## Summary
Nodes represent task instances. They consume typed input, call a provider, and emit typed output.

## When to use
Use nodes for AI inference, integrations, transforms, human review, and control operations.

## Core idea
Nodes execute work only. Routing and orchestration logic belongs to edges and runtime scheduling.

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
```

## Common mistakes
- Duplicating business routing logic inside provider code.
- Leaving `config_schema` and outputs underspecified.

## Related pages
- [Edges Concept](edges.md)
- [Provider Interface](../reference/provider_interface.md)
- [Add AI Step Guide](../guides/add_ai_step.md)
