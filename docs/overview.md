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

---

# Design Philosophy

## AI systems are operational systems

BPG is built on the core principle that **AI systems are operational systems, not just prompt pipelines.**

The difficult problems in production AI systems are not the LLM generation itself, but the operational concerns surrounding it:
* Orchestration and state management
* Retries and error recovery
* Human-in-the-loop approvals
* Observability and auditability
* Deployment and governance

BPG exists to solve these operational problems by treating LLMs as execution components within larger governed workflows.

## Opinionated Semantics, Flexible Integrations

BPG is **strongly opinionated about workflow semantics**. It defines canonical behavior for:
* Workflow lifecycle and state transitions
* Retry and compensation logic
* Pause/resume and human approval flows
* Execution lineage and audit trails

At the same time, BPG is **flexible about integrations**. It intentionally avoids hard dependencies on specific cloud providers, LLM vendors, or vector databases. It defines the interface contracts, while allowing you to select the implementations (e.g., OpenAI vs. Anthropic, Weaviate vs. OpenSearch).

## System Layers

1. **Workflow Runtime:** Responsible for graph execution, scheduling, and durable state persistence. BPG uses Temporal for reliable, long-running execution.
2. **Node System:** Nodes are typed, observable units of work with explicit inputs and outputs.
3. **Observability Layer:** A first-class concern. Workflows and nodes emit canonical
   events that project to OpenTelemetry traces and a Postgres audit ledger when
   `observability` is enabled on a process.
4. **Human-in-the-loop (HITL):** Human intervention is a first-class orchestration primitive, not an afterthought.

## Node Philosophy

BPG distinguishes between **Core Nodes** (universal fundamental operations like branch,
transform, log) and **Extension Packages** (vendor-specific or domain-specific
functionality). First-party extension packages (`bpg-nodes-ai`, `bpg-nodes-search`, and
others) are published in the
[bpg-marketplace](https://github.com/ginstrom/bpg-marketplace) registry.

This separation avoids dependency bloat and vendor lock-in while keeping the core
framework stable.

## Related pages
- [Quickstart](quickstart.md)
- [Process Concept](concepts/process.md)
- [Traceability and Auditability](design/traceability-and-auditability.md)
- [Marketplace](marketplace/index.md)
- [How Agents Should Use BPG](ai/how_agents_should_use_bpg.md)
