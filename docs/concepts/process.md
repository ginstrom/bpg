# Process Concept

```yaml
doc_metadata:
  topic: process
  version: 1
  summary: A process is the canonical deployable unit in BPG.
```

## Summary
A process is a typed graph specification that defines nodes, edges, trigger, and optional output/policy metadata. It can also import shared definitions and define internal modules for reuse.

## When to use
Use one process per coherent business flow that needs independent versioning and lifecycle management.

## Core idea
The process is the top-level contract. Everything else (validation, planning, execution, replay) derives from it.

### Shared Definitions (Imports)
Processes can import `types`, `node_types`, and `modules` from other BPG files to promote reuse across multiple business flows.

### Reusable Components (Modules)
Modules allow developers to group nodes and edges into a named, reusable component within a process. Modules define their own input and output interfaces, acting as "sub-processes" that can be instantiated as nodes.

## Example
```yaml
metadata:
  name: support_flow
  version: 0.1.0

imports:
  - common_types.bpg.yaml
  - standard_node_types.bpg.yaml

modules:
  risk_check:
    inputs:
      data: object
    nodes:
      verify: { type: mock@v1, config: {} }
    edges:
      - from: __input__
        to: verify
    outputs:
      risk: verify.out.risk
    version: 1.0.0

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
