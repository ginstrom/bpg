# Node Schema Reference

```yaml
doc_metadata:
  topic: node_schema
  version: 1
  summary: Node types define interfaces; nodes bind those interfaces to concrete config.
```

## Summary
`node_types` declare typed contracts and providers; `nodes` instantiate them.

## When to use
Use for provider integration design and enforcing stable in/out contracts.

## Core idea
The node type is the reusable contract. Node instances are deployment-time bindings.

## Example
```yaml
node_types:
  extract@v1:
    in: DocIn
    out: ExtractOut
    provider: mock
    version: v1
    config_schema:
      model: string?

nodes:
  extract:
    type: extract@v1
    config:
      model: sample
```

## Common mistakes
- Mismatching `type` references or versions.
- Treating `config_schema` as optional when providers require fields.

## Related pages
- [Provider Interface](provider_interface.md)
- [Type System](type_system.md)
- [Nodes Concept](../concepts/nodes.md)
