# BPG Overview

```yaml
doc_metadata:
  topic: overview
  version: 1
  summary: BPG is an AI-first framework for designing reliable business process graphs.
```

## Summary
BPG lets AI agents and developers define business systems as typed process graphs instead of custom orchestration code.

## When to use
Use BPG when you need deterministic process execution, explicit data flow, and validation feedback that supports iterative AI-assisted authoring.

## Core idea
BPG treats process design as a structured interface:

Process -> Nodes -> Edges -> Execution.

BPG validates the graph, reports machine-actionable diagnostics, and runs the process with stable semantics.
It persists run outputs/events and can materialize declared output artifacts (`json`, `jsonl`, `csv`) for downstream systems.

## Example
```yaml
metadata:
  name: document_pipeline
  version: 0.1.0

types:
  DocIn:
    text: string
  ClassifyOut:
    label: string
    confidence: number

node_types:
  trigger@v1:
    in: object
    out: DocIn
    provider: dashboard.form
    version: v1
    config_schema: {}
  classify@v1:
    in: DocIn
    out: ClassifyOut
    provider: mock
    version: v1
    config_schema: {}

nodes:
  input:
    type: trigger@v1
    config: {}
  classify:
    type: classify@v1
    config: {}

trigger: input

edges:
  - from: input
    to: classify
    with:
      text: trigger.in.text
```

## Common mistakes
- Treating BPG as a generic scripting language instead of a constrained process DSL.
- Hiding routing logic in providers instead of explicit `edges.when` conditions.
- Relying on implicit field passing instead of explicit `edge.with` mappings.

## Related pages
- [Quickstart](quickstart.md)
- [Process Concept](concepts/process.md)
- [How Agents Should Use BPG](ai/how_agents_should_use_bpg.md)
