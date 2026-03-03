# Process Concept

```yaml
doc_metadata:
  topic: process
  version: 1
  summary: A process is the canonical deployable unit in BPG.
```

## Summary
A process is a typed graph specification that defines nodes, edges, trigger, and optional output/policy metadata.

## When to use
Use one process per coherent business flow that needs independent versioning and lifecycle management.

## Core idea
The process is the top-level contract. Everything else (validation, planning, execution, replay) derives from it.

## Example
```yaml
metadata:
  name: support_flow
  version: 0.1.0
types: {}
node_types: {}
nodes: {}
trigger: start
edges: []
```

## Common mistakes
- Mixing unrelated workflows into one oversized process.
- Changing process names casually, which breaks stable references.

## Related pages
- [Nodes Concept](nodes.md)
- [Edges Concept](edges.md)
- [Process Schema](../reference/process_schema.md)
