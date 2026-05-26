# BPG System Design and Philosophy

## Overview

BPG is a workflow orchestration framework for building reliable, observable, and governable AI-native systems.

The framework is designed around a core principle:

> AI systems are operational systems, not just prompt pipelines.

BPG focuses on:

* durable workflow execution
* typed orchestration
* human-in-the-loop operations
* observability and auditability
* production delivery workflows
* AI system governance
* composable execution primitives

The framework is intentionally designed for:

* enterprise environments
* production workflows
* operational reliability
* long-running execution
* integration with existing infrastructure
* deterministic orchestration around nondeterministic AI systems

BPG is not intended to be:

* a no-code platform
* a simple agent loop framework
* a prompt wrapper
* a chatbot builder
* a monolithic AI platform

---

# Core Philosophy

## AI generation is not the hard part

The difficult problems in production AI systems are:

* orchestration
* retries
* state management
* approvals
* observability
* rollback
* auditability
* deployment
* governance
* recovery
* long-running execution

BPG exists to solve these operational problems.

LLMs are treated as execution components within larger governed workflows.

---

# Architectural Philosophy

## Strongly opinionated about workflow semantics

BPG defines canonical behavior for:

* workflow lifecycle
* retries
* state transitions
* pause/resume
* approvals
* tracing
* auditability
* failure semantics
* compensation/rollback
* execution lineage

These are foundational framework guarantees.

Without consistent semantics:

* workflows become incompatible
* tooling becomes fragmented
* observability breaks down
* governance becomes unreliable

---

## Flexible about integrations and implementations

BPG intentionally avoids hard dependency on:

* specific cloud providers
* specific vector databases
* specific LLM vendors
* specific notification systems
* specific deployment targets

The framework defines interfaces and abstractions while allowing users to select implementations.

Examples:

* OpenAI / Anthropic / Gemini
* Weaviate / OpenSearch / Qdrant
* Slack / Teams / email
* Kubernetes / ECS / Docker Compose

---

# System Layers

## 1. Workflow Runtime

Responsible for:

* graph execution
* scheduling
* state persistence
* retries
* compensation
* durable execution
* pause/resume
* orchestration

BPG may integrate with durable workflow engines such as:

* [Temporal](https://temporal.io?utm_source=chatgpt.com)

BPG orchestrates workflows rather than replacing existing infrastructure platforms.

---

## 2. Node System

Nodes are typed, observable units of work.

A node should have:

* explicit inputs
* explicit outputs
* validation
* observable execution
* failure semantics
* retry semantics
* side-effect declarations

Nodes are intended to be:

* composable
* testable
* reusable
* inspectable
* traceable

---

## 3. Observability Layer

Observability is a first-class concern.

All workflows and nodes should emit:

* traces
* metrics
* structured logs
* execution lineage
* audit events

This should happen automatically through the framework.

The goal is:

* operational debugging
* execution replay
* governance visibility
* compliance support
* AI explainability

The framework is designed to integrate with systems such as:

* OpenTelemetry
* Grafana
* Loki
* Tempo

---

## 4. Human-in-the-Loop (HITL)

Human approval and intervention are core workflow concepts.

HITL is treated as a first-class orchestration primitive rather than an application-specific hack.

BPG defines canonical semantics for:

* approval requests
* workflow suspension
* workflow resume
* escalation
* timeout handling
* actor identity
* audit trails
* multi-stage approvals

Example:

```python
HumanApprovalNode(
    approvers=["role:security"],
    timeout="24h",
    escalation="manager",
    required_votes=1,
)
```

This model enables:

* enterprise governance
* regulated workflows
* safe AI deployment
* operational accountability

---

# Node Philosophy

## Core vs Extensions

BPG distinguishes between:

* core framework nodes
* first-party extension packages
* third-party/custom nodes

---

# Core Nodes

Core nodes should be:

* universal
* stable
* dependency-light
* operationally fundamental

Examples:

* Sequence
* Parallel
* Retry
* Branch
* Transform
* Validate
* HumanApproval
* Log
* Assert
* HttpRequest

The core package should remain relatively small and stable.

---

# Extension Packages

Vendor-specific or domain-specific functionality should live in extension packages.

Examples:

```text
bpg-nodes-llm
bpg-nodes-rag
bpg-nodes-vectorstores
bpg-nodes-devops
bpg-nodes-cloud
```

Examples of extension nodes:

* WeaviateSearch
* OpenSearchHybridSearch
* KubernetesDeploy
* GitLabCreateMR
* SlackNotification
* OpenAICompletion

This avoids:

* dependency bloat
* unstable APIs in core
* vendor lock-in
* framework fragmentation

---

# Node Authoring Philosophy

Writing custom nodes should be extremely easy.

---

# Simple Function Nodes

Simple nodes should require minimal boilerplate.

Example:

```python
from bpg import node

@node
def add_prefix(text: str, prefix: str) -> str:
    return prefix + text
```

The framework should automatically provide:

* validation
* tracing
* schema generation
* execution wrapping
* metadata extraction

---

# Typed Production Nodes

More advanced nodes may use explicit class-based definitions.

Example:

```python
from bpg import Node, Input, Output

class EmbedText(Node):
    input = Input({
        "text": str,
        "model": str,
    })

    output = Output({
        "embedding": list[float],
    })

    async def run(self, ctx, input):
        ...
```

---

# Plugin Architecture

Node libraries should be distributable independently.

Example:

```bash
uv add bpg-nodes-weaviate
```

Automatic node discovery should be supported.

---

# Opinionated vs Flexible Areas

## Strongly Opinionated Areas

BPG should strongly define:

* workflow lifecycle semantics
* retries
* idempotency
* pause/resume
* approvals
* tracing
* execution lineage
* failure semantics
* compensation behavior
* auditability

These are foundational platform guarantees.

---

## Blessed Interfaces

BPG should provide standardized abstractions for:

* notifications
* authentication
* storage
* deployment
* LLM providers
* vector databases

The framework owns the interface contracts while users select implementations.

Example:

```python
Notify(
    channel="approval_required",
    template="deploy_waiting",
)
```

Possible implementations:

* Slack
* Teams
* email
* webhook
* PagerDuty

---

## Intentionally Unopinionated Areas

BPG should avoid rigid standards for:

* prompt engineering strategies
* agent reasoning styles
* vector DB selection
* model vendor selection
* specific AI architectural patterns

These evolve too quickly and should remain flexible.

---

# Enterprise Design Goals

BPG is designed to support:

* auditability
* reproducibility
* rollback safety
* operational governance
* long-running workflows
* regulated workflows
* explainability
* human oversight
* deployment automation

The framework is intended to support:

* enterprise AI systems
* production AI operations
* AI-native SDLC workflows
* autonomous delivery systems with human supervision

---

# Recommended Ecosystem Positioning

BPG should be positioned as:

> AI workflow orchestration and operational governance infrastructure.

Not:

* an AI coding assistant
* a no-code automation tool
* a chatbot framework
* a prompt engineering toolkit

The primary value proposition is:

* operational reliability
* workflow orchestration
* enterprise governance
* production AI delivery

---

# Long-Term Vision

The long-term direction of BPG is toward:

* AI delivery orchestration
* enterprise AI SDLC
* autonomous but governable workflows
* human-supervised automation
* observable AI operations
* reusable workflow capabilities
* production-safe AI systems

The framework aims to provide the operational foundation for enterprise-grade AI systems rather than focusing solely on model interaction or code generation.

