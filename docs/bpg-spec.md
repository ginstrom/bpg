# Business Process Graph (BPG) Specification

**Version:** 0.2 (Draft)
**Status:** In Review

---

## Table of Contents

1. [Overview](#1-overview)
2. [Design Philosophy](#2-design-philosophy)
3. [Core Concepts](#3-core-concepts)
   - 3.1 [Types](#31-types)
   - 3.2 [Node Types](#32-node-types)
   - 3.3 [Providers](#33-providers)
4. [Process Definition](#4-process-definition)
   - 4.1 [Node Instances](#41-node-instances)
   - 4.2 [Edges](#42-edges)
   - 4.3 [Data Mapping](#43-data-mapping)
   - 4.4 [Trigger](#44-trigger)
   - 4.5 [Process Output](#45-process-output)
5. [Compilation & Plan Phase](#5-compilation--plan-phase)
6. [Apply Phase](#6-apply-phase)
7. [Runtime Execution Model](#7-runtime-execution-model)
8. [Idempotency](#8-idempotency)
9. [Human-in-the-Loop Nodes](#9-human-in-the-loop-nodes)
10. [Error Handling & Retries](#10-error-handling--retries)
11. [Versioning & Breaking Changes](#11-versioning--breaking-changes)
12. [Modules](#12-modules)
13. [Security & Policy](#13-security--policy)
14. [Execution Guarantees](#14-execution-guarantees)
15. [Future Extensions](#15-future-extensions)
   - 15.1 [Near-Term Delivery Priorities](#151-near-term-delivery-priorities)
16. [Full Example: Bug Triage Process](#16-full-example-bug-triage-process)
17. [Operational Packaging & Local Runtime (Implemented)](#17-operational-packaging--local-runtime-implemented)
18. [Search Pipelines Pattern (Implemented Baseline)](#18-search-pipelines-pattern-implemented-baseline)

---

## 1. Overview

Business Process Graph (BPG) is a declarative, infrastructure-as-code system for defining, deploying, and executing business processes as typed execution graphs.

BPG applies proven patterns from infrastructure tooling — explicit state, plan/apply lifecycle, type-safe contracts — to the problem of automating and auditing complex business workflows. Processes are versioned, diffable, and reproducible.

A BPG process consists of:

- **Types** — strongly typed schemas for all node inputs and outputs
- **Node Types** — reusable, versioned execution component definitions
- **Node Instances** — configured deployments of node types within a process
- **Edges** — explicit, conditional directed relationships between nodes
- **Providers** — pluggable execution backends (agents, humans, external APIs)
- **Runtime** — a deterministic, idempotent, event-driven execution engine

The system separates three distinct concerns:

| Layer | Responsibility |
|---|---|
| **Definition** | Process as code (DSL) |
| **Deployment** | Plan, apply, and state management |
| **Execution** | Event-driven DAG runtime |

---

## 2. Design Philosophy

BPG is guided by the following principles:

**Declarative over imperative.** Processes describe *what* should happen, not *how* to orchestrate it. The runtime owns sequencing.

**Explicit over implicit.** All data flow, conditions, and dependencies must be declared. No hidden control flow.

**Strong typing everywhere.** All node boundaries are schema-enforced. Type violations are caught at compile time, not runtime.

**Idempotent by default.** Every node invocation is keyed and safe to retry. Side effects are not duplicated.

**Auditable by design.** Every run produces an immutable, append-only execution log. There is always a record of what happened and why.

**Operator-friendly lifecycle.** Processes support `plan` to preview changes and `apply` to deploy them, just as infrastructure does.

---

## 3. Core Concepts

### 3.1 Types

All node inputs and outputs MUST be defined as named, structured types registered in a global type registry.

#### Primitive Types

| Type | Description |
|---|---|
| `string` | UTF-8 text |
| `number` | 64-bit float |
| `bool` | `true` or `false` |
| `enum(A,B,C)` | Closed set of string values |
| `duration` | Duration string. Runtime currently supports literals like `500ms`, `30s`, `5m`, `2h`, `1d` |
| `datetime` | ISO 8601 timestamp |
| `object` | Nested key-value map |
| `list<T>` | Ordered list of a typed element |
| `T?` | Optional field; omission is valid |

#### Type Declaration

```yaml
types:
  BugReport:
    title: string
    severity: enum(S1,S2,S3)
    description: string
    reporter_email: string?

  TriageResult:
    risk: enum(low,med,high)
    summary: string
    labels: list<string>
    recommended_assignee: string?
```

#### Type Rules

- Type definitions are **immutable once published**. Breaking changes require a new versioned type (e.g., `BugReport@v2`).
- Types may be shared across processes and modules.
- Inline anonymous types are not permitted. All types must be named and registered.

---

### 3.2 Node Types

Node types define reusable, versioned execution components. They declare the interface contract and provider binding for a class of work.

A node type MUST declare:

| Field | Required | Description |
|---|---|---|
| `in` | Yes | Input type name |
| `out` | Yes | Output type name |
| `provider` | Yes | Provider identifier |
| `config_schema` | Yes | Configuration schema for instances |
| `version` | Yes | Semantic version string |
| `description` | No | Human-readable summary |
| `timeout_default` | No | Default execution timeout |

#### Example

```yaml
node_types:
  triage_agent@v1:
    description: "Classifies an incoming bug report by risk level and generates a summary."
    in: BugReport
    out: TriageResult
    provider: agent.pipeline
    timeout_default: 5m
    config_schema:
      pipeline: string
      model: string?

  slack_approval@v1:
    description: "Sends an interactive approval request to a Slack channel."
    in: ApprovalRequest
    out: ApprovalDecision
    provider: slack.interactive
    timeout_default: 24h
    config_schema:
      channel: string
      buttons: list<string>
      timeout: duration

  gitlab_issue_create@v1:
    description: "Creates a new issue in a GitLab project."
    in: IssueRequest
    out: IssueResult
    provider: http.gitlab
    config_schema:
      project_id: string
      default_labels: list<string>?
```

Node types define contracts. Node instances inherit them and cannot override the input/output schema.

---

### 3.3 Providers

Providers are pluggable execution backends responsible for carrying out work on behalf of a node.

#### Built-in Provider Types

| Provider ID | Category | Description |
|---|---|---|
| `agent.pipeline` | AI/Automation | Invokes an AI agent pipeline |
| `slack.interactive` | Human | Posts interactive messages to Slack |
| `dashboard.form` | Human | Renders a web form for structured input |
| `http.webhook` | Integration | Sends/receives HTTP callbacks |
| `http.gitlab` | Integration | GitLab REST API operations |
| `queue.kafka` | Messaging | Publishes/consumes Kafka messages |
| `timer.delay` | Control | Waits a specified duration |
| `mock` | Testing | Deterministic canned outputs for local/system tests |

Search-oriented providers (`fs.markdown_list`, `text.markdown_chunk`, `embed.text`, `weaviate.upsert`, `weaviate.hybrid_search`) are available as baseline built-ins and specified in §18.

#### Provider Contract

All providers MUST implement the following interface:

```
invoke(input: TypedPayload, config: ProviderConfig, context: ExecutionContext) -> ExecutionHandle
poll(handle: ExecutionHandle) -> ExecutionStatus
await_(handle: ExecutionHandle, timeout: Duration) -> TypedOutput
cancel(handle: ExecutionHandle) -> void
```

Python uses `await_` because `await` is a reserved keyword. Providers may also expose `await_result` for compatibility.

All providers MUST:

- Accept and honor idempotency keys
- Produce structured, schema-conformant output
- Surface errors as typed `ProviderError` values, not panics
- Be stateless with respect to process logic (all state lives in BPG runtime)

---

## 4. Process Definition

A process file declares the full configuration of a deployable business process.

```
process.bpg.yaml
```

A process file MUST contain:

- `types` (inline or via import)
- `nodes`
- `edges`
- `trigger`

A process file MAY contain:

- `output`
- `metadata`
- `policy`

---

### 4.1 Node Instances

Node instances bind a node type to concrete configuration for use in a specific process.

```yaml
nodes:
  triage:
    type: triage_agent@v1
    description: "Initial AI triage of incoming bug reports."
    config:
      pipeline: triage_v2
      model: gpt-4o

  approval:
    type: slack_approval@v1
    description: "Engineering lead approval for high-risk bugs."
    config:
      channel: "#ops-approvals"
      buttons: [Approve, Reject]
      timeout: 24h
    on_timeout:
      out:
        approved: false
        reason: "No response within 24h — auto-rejected."

  gitlab:
    type: gitlab_issue_create@v1
    config:
      project_id: "myorg/backend"
      default_labels: ["bug"]
```

Node instances MUST NOT override `in` or `out` types.

---

### 4.2 Edges

Edges define directed execution relationships between nodes. Each edge represents a conditional call from one node to another, with optional data mapping.

An edge MUST declare:

| Field | Required | Description |
|---|---|---|
| `from` | Yes | Source node name |
| `to` | Yes | Target node name |
| `when` | No | Boolean condition; if omitted, edge is unconditional |
| `with` | No | Data mapping for target's input |
| `timeout` | No | Override for this edge's execution timeout |
| `on_failure` | No | Behavior if the target node fails |

#### Example

```yaml
edges:
  - from: triage
    to: approval
    when: triage.out.risk == "high"
    with:
      title: "High-risk bug: {{triage.out.summary}}"
      risk_level: triage.out.risk
      reporter: trigger.in.reporter_email

  - from: triage
    to: gitlab
    when: triage.out.risk != "high"
    with:
      title: triage.out.summary
      labels: triage.out.labels

  - from: approval
    to: gitlab
    when: approval.out.approved == true
    with:
      title: triage.out.summary
      labels: triage.out.labels
    on_failure:
      action: notify
      node: notify_reporter
```

#### Conditional Expression Syntax

The `when` field supports:

- Equality: `==`, `!=`
- Comparisons: `>`, `<`, `>=`, `<=`
- Boolean algebra: `&&`, `||`, `!`
- Null check: `is_null(expr)`, `is_present(expr)`
- String interpolation in `with` values: `"{{expr}}"`

No arbitrary scripting or function calls are permitted in edge expressions.

---

### 4.3 Data Mapping

The `with` block maps source values to target node inputs.

#### Rules

- The mapping MUST fully satisfy the target node's `in` type.
- All required fields MUST be provided via mapping or literal value.
- Optional fields (`T?`) may be omitted.
- Extra fields not in the target schema MUST cause a plan-time failure.
- Field references take the form `<node_name>.out.<field>` or `trigger.in.<field>`.
- Literal values (strings, numbers, booleans) are valid on the right-hand side.

#### Example

```yaml
with:
  title: "Bug: {{triage.out.summary}}"   # string interpolation
  severity: trigger.in.severity          # reference to trigger input
  approved: true                         # literal value
  assignee: triage.out.recommended_assignee  # optional field passthrough
```

---

### 4.4 Trigger

Every process MUST declare exactly one trigger node. The trigger is the entry point for a process run and receives the initial input payload.

```yaml
trigger: intake_form
```

Trigger nodes:

- MUST have no incoming edges
- MUST be a declared node instance
- Receive external input that MUST conform to the trigger node's `in` type

---

### 4.5 Process Output

A process MAY declare an output value. This is the value returned to a calling system when the process completes.

```yaml
output: gitlab.out.ticket_id
```

The output MUST reference a field from a completed node's output. If the referenced node did not execute (e.g., its `when` condition was false), the process output is `null`.

---

## 5. Compilation & Plan Phase

Before deployment, the compiler validates the process definition and generates a plan diff against the current deployed state.

#### Compilation Steps

1. Parse and validate DSL syntax
2. Resolve all type references; fail on unknown types
3. Resolve all node type references; fail on unknown or mismatched versions
4. Type-check all edge `with` mappings against target `in` schemas
5. Validate all `when` expressions are syntactically valid
6. Detect cycles in the execution graph (loops require explicit loop constructs — see §15)
7. Validate all provider configs against their declared `config_schema`
8. Generate execution Intermediate Representation (IR)
9. Diff IR against persisted state to produce a plan

#### Plan Output Format

```
BPG Plan: bug-triage-process

  ~ process "bug-triage-process"
      version: "1.3.0" -> "1.4.0"

  + node "notify_reporter" (slack_notification@v1)
      config.channel: "#engineering"

  ~ node "approval"
      config.timeout: "24h" -> "48h"

  ~ edge "triage -> gitlab"
      when: 'triage.out.risk != "high"'
             -> 'triage.out.risk == "low" || triage.out.risk == "med"'

  No type changes.
  No provider artifact changes.

Plan: 1 to add, 2 to change, 0 to destroy.
```

No execution occurs during plan. Plan output is deterministic and repeatable.

#### Plan Artifact Inspection

BPG MAY emit a machine-readable plan artifact:

- `bpg plan <process_file> --out plan.out`
- `bpg show --json plan.out`

The artifact includes:

- Change summary (`added_nodes`, `modified_nodes`, `removed_nodes`, edge deltas, trigger change)
- IR delta (old/new node and edge counts, topological order)
- Artifact preview for added/modified/removed nodes

This enables CI and scripting workflows (for example, piping to `jq`).

---

## 6. Apply Phase

Apply deploys the planned changes to the BPG runtime and all associated provider backends.

#### Apply Steps

1. Validate plan is up-to-date against current state (fail if state has drifted)
2. Register updated process definition and execution IR
3. Deploy or update provider artifacts (Slack app configurations, webhooks, dashboard forms, etc.)
4. Persist new process version hash and node type version pins
5. Persist provider state references (e.g., Slack action IDs, webhook endpoint URLs)
6. Emit apply summary

Apply MUST be idempotent. Re-running apply on an already-applied plan MUST produce no changes and no side effects.

In-flight process runs are NOT interrupted by apply. Runs execute against the version of the process that was active when they were triggered. New runs pick up the newly applied version.

---

## 7. Runtime Execution Model

Execution is event-driven. Nodes execute as their dependencies complete and their incoming edge conditions are satisfied.

#### Process Run Lifecycle

Each process run has:

- A unique, globally unique `run_id`
- An immutable, append-only execution log
- A per-node execution record (status, input, output, timestamps, idempotency key)

#### Node Execution Semantics

For each node in a run:

1. **Wait** — block until all nodes with edges pointing to this node have completed (or been skipped)
2. **Evaluate** — check all incoming `when` conditions; if none are satisfied, mark node as `skipped`
3. **Map** — assemble the input payload from `with` mappings
4. **Validate** — assert input conforms to node's `in` type
5. **Invoke** — call provider with input, config, and execution context (including idempotency key)
6. **Await** — wait for provider to return output, subject to timeout
7. **Validate** — assert output conforms to node's `out` type
8. **Persist** — write result to execution log; mark node as `completed`

#### Node Statuses

| Status | Description |
|---|---|
| `pending` | Waiting for dependencies |
| `running` | Provider invoked, awaiting result |
| `completed` | Successfully finished |
| `skipped` | All incoming `when` conditions were false |
| `failed` | Provider returned an error |
| `timed_out` | Execution exceeded timeout |
| `cancelled` | Run was cancelled before completion |

---

## 8. Idempotency

All node invocations MUST be idempotent.

#### Idempotency Key Generation

```
idempotency_key = sha256(run_id + ":" + node_name + ":" + canonical_json(stable_input_fields))
```

`stable_input_fields` are the fields of the input payload that are marked stable (i.e., not time- or nonce-derived). By default, all fields are considered stable.

Providers MUST:

- Accept an `idempotency_key` in every invocation
- Return the same result for repeated invocations with the same key
- NOT create duplicate side effects (e.g., duplicate Slack messages, duplicate GitLab issues)

The BPG runtime MAY cache provider results keyed on `idempotency_key` to avoid redundant provider calls on retry.

---

## 9. Human-in-the-Loop Nodes

Human nodes are first-class citizens in BPG. They are regular node types whose provider presents an interactive interface to a human actor and awaits a structured response.

Human node providers include `slack.interactive` and `dashboard.form`.

#### Timeout Handling

All human nodes MUST declare a `timeout` in their config and a corresponding `on_timeout` behavior on the node instance.

```yaml
nodes:
  approval:
    type: slack_approval@v1
    config:
      channel: "#ops-approvals"
      buttons: [Approve, Reject]
      timeout: 48h
    on_timeout:
      out:
        approved: false
        reason: "Auto-rejected: no response within 48 hours."
```

`on_timeout.out` MUST satisfy the node's `out` type schema. The run continues with this synthetic output.

#### Free-Text Input

When a human node must collect free-form text, the response MUST still be schema-wrapped:

```yaml
types:
  ReviewComment:
    body: string
    sentiment: enum(positive,neutral,negative)?
```

Free-text fields are typed as `string`. Downstream nodes receive a structured payload regardless.

---

## 10. Error Handling & Retries

BPG provides structured error handling at the node and edge level.

#### Node-Level Retry Policy

```yaml
nodes:
  triage:
    type: triage_agent@v1
    config:
      pipeline: triage_v2
    retry:
      max_attempts: 3
      backoff: exponential
      initial_delay: 5s
      max_delay: 60s
      retryable_errors: [rate_limit, transient_failure]
```

#### Edge-Level Failure Routing

Edges can route to a fallback node on failure:

```yaml
edges:
  - from: triage
    to: gitlab
    when: triage.out.risk != "high"
    with:
      title: triage.out.summary
    on_failure:
      action: route
      to: notify_reporter
```

#### Process-Level Failure Behavior

If a node exhausts retries and has no failure route, the process run transitions to `failed`. The execution log retains all completed node outputs up to the point of failure.

---

## 11. Versioning & Breaking Changes

#### Node Types

Node type versions follow semantic versioning. A new version MUST be published when:

- `in` or `out` type schema changes in a breaking way (field removed, type narrowed, field made required)
- `config_schema` changes in a breaking way

Non-breaking additive changes (adding optional fields) MAY be applied in-place with a patch version bump.

#### Types

Types are immutable once published. Breaking changes require a new versioned type name:

```
BugReport     # original
BugReport@v2  # breaking change
```

#### Processes

Processes MUST pin explicit node type versions:

```yaml
nodes:
  triage:
    type: triage_agent@v1
```

The BPG state store persists:

- Current process definition hash
- All pinned node type versions
- All pinned type versions
- All provider artifact references and their checksums

Upgrading a node type version requires an explicit process definition change, followed by plan and apply.

---

## 12. Modules

Modules allow reusable process fragments to be extracted, versioned, and shared across processes.

A module defines:

- Named input parameters
- Internal node instances (scoped to the module)
- Exported outputs

```yaml
module: risk_routing@v1
  description: "Routes a triage result to either approval or direct filing."
  
  inputs:
    triage_result: TriageResult
    reporter_email: string

  nodes:
    approval:
      type: slack_approval@v1
      config:
        channel: "#ops-approvals"
        buttons: [Approve, Reject]
        timeout: 24h

    gitlab:
      type: gitlab_issue_create@v1
      config:
        project_id: "myorg/backend"

  edges:
    - from: __input__
      to: approval
      when: triage_result.risk == "high"
      with:
        title: "{{triage_result.summary}}"
        risk_level: triage_result.risk

    - from: __input__
      to: gitlab
      when: triage_result.risk != "high"
      with:
        title: triage_result.summary

    - from: approval
      to: gitlab
      when: approval.out.approved == true

  outputs:
    ticket_id: gitlab.out.ticket_id
```

Modules are referenced in processes like node instances. Modules MUST be versioned and follow the same breaking change rules as node types.

---

## 13. Security & Policy

Policy can be attached at the process, node, or edge level.

```yaml
policy:
  access_control:
    - node: approval
      allowed_roles: [engineering_lead, on_call_manager]

  separation_of_duties:
    - reporter_cannot_approve: true

  pii_redaction:
    - node: triage
      redact_fields: [reporter_email]

  audit:
    - retain_run_logs_for: 365d
    - export_to: splunk.audit_sink
```

#### Supported Policy Types

| Policy | Description |
|---|---|
| `access_control` | Restrict who may act on a human node |
| `separation_of_duties` | Prevent the same principal from fulfilling multiple roles |
| `pii_redaction` | Redact specified fields in execution logs |
| `escalation` | Define escalation paths on timeout or failure |
| `audit` | Log retention, export, and compliance tagging |

---

## 14. Execution Guarantees

#### What BPG Guarantees

- Deterministic execution ordering derived from the declared graph structure
- Strong input/output type enforcement at every node boundary
- Idempotent side effects via provider-level idempotency keys
- Immutable, append-only run history
- Provider isolation — providers cannot access each other's state or other runs
- Plan/apply separation — no execution occurs during plan

#### What BPG Does Not Guarantee

- Real-time or low-latency execution (latency is governed by provider and human response times)
- External system reliability (provider failures surface as node errors, not BPG failures)
- Deterministic outputs from non-deterministic providers (e.g., LLM-based agents) — only schema conformance is guaranteed
- Transactional rollback across multiple completed nodes (compensation is a future extension — see §15)

---

## 15. Future Extensions

### 15.1 Near-Term Delivery Priorities

To preserve the core BPG goal as a **business process as code** system with Terraform-like operator ergonomics, the following implementation priorities are in scope for the next delivery phases:

1. Runtime and execution lifecycle completion
   - Implement production `run`/`status` CLI and engine APIs with persisted run records.
   - Enforce runtime input/output type validation at trigger and node boundaries.
   - Ensure timeout fallback (`on_timeout.out`) continues execution for human nodes.
   - Surface process-level failed terminal state when retries are exhausted with no failure route.
2. State, plan/apply, and drift hardening
   - Complete run/node persistence APIs in the state store with append-only run history semantics.
   - Strengthen apply drift detection and persist execution IR/version pins/artifact references and checksums.
   - Improve plan output to cover IR-level and provider-artifact deltas deterministically.
3. Compile-time contract enforcement improvements
   - Expand provider config validation from key presence to schema-typed validation.
   - Enforce edge mapping completeness for required target input fields, including when `with` is omitted.
   - Support literal mapping values beyond strings (number/bool) and keep strict reference validation.
4. Versioning and model alignment
   - Enforce explicit node type version contract semantics and compatibility rules.
   - Enforce published type immutability/version-bump rules at apply boundaries.
   - Validate process output references and nullability behavior when referenced nodes do not execute.
5. Remaining major spec surfaces
   - Implement module authoring/consumption model (§12).
   - Implement policy schema + enforcement hooks for access control, SoD, PII redaction, escalation, and audit (§13).
   - Expand end-to-end tests for runtime lifecycle, timeout continuation, failure behavior, policy, and modules.

The following are planned or under consideration for future versions of the specification:

| Feature | Description |
|---|---|
| **Loop constructs** | Bounded iteration over a list or until a condition is met |
| **Parallel fanout** | Invoke multiple nodes in parallel and await all or any |
| **Subgraph transactions** | Treat a set of nodes as an atomic unit |
| **Compensation (Saga)** | Define rollback actions for already-completed nodes on downstream failure |
| **Dynamic routing** | Runtime-resolved edge targets based on output values |
| **Rate limiting** | Per-provider or per-process invocation rate controls |
| **Cost estimation** | Plan-time estimation of execution cost based on provider pricing |
| **Event sourcing integration** | Emit run events to external event buses |
| **Cross-process calls** | Invoke another BPG process as a node |

---

## 16. Full Example: Bug Triage Process

A complete, runnable process demonstrating most BPG features.
These YAML examples are validated by system tests to prevent doc/spec drift.

```yaml
# types.bpg.yaml

types:
  BugReport:
    title: string
    severity: enum(S1,S2,S3)
    description: string
    reporter_email: string?

  TriageResult:
    risk: enum(low,med,high)
    summary: string
    labels: list<string>
    recommended_assignee: string?

  ApprovalRequest:
    title: string
    risk_level: enum(low,med,high)
    reporter: string?

  ApprovalDecision:
    approved: bool
    reason: string?

  IssueRequest:
    title: string
    labels: list<string>
    assignee: string?

  IssueResult:
    ticket_id: string
    url: string
```

```yaml
# node_types.bpg.yaml

node_types:
  triage_agent@v1:
    description: "Classifies a bug report and generates a risk assessment."
    in: BugReport
    out: TriageResult
    provider: agent.pipeline
    version: v1
    timeout_default: 5m
    config_schema:
      pipeline: string
      model: string?

  slack_approval@v1:
    description: "Sends an interactive approval prompt to a Slack channel."
    in: ApprovalRequest
    out: ApprovalDecision
    provider: slack.interactive
    version: v1
    timeout_default: 24h
    config_schema:
      channel: string
      buttons: list<string>
      timeout: duration

  gitlab_issue_create@v1:
    description: "Opens a new issue in a GitLab project."
    in: IssueRequest
    out: IssueResult
    provider: http.gitlab
    version: v1
    config_schema:
      project_id: string
      default_labels: list<string>?

  dashboard.form@v2:
    description: "Web form provider."
    in: BugReport
    out: BugReport
    provider: dashboard.form
    version: v2
    config_schema:
      title: string
      schema: string
```

```yaml
# process.bpg.yaml

metadata:
  name: bug-triage-process
  version: 1.4.0
  description: "End-to-end bug ingestion, triage, approval, and issue creation."
  owner: platform-eng@myorg.com

nodes:
  intake_form:
    type: dashboard.form@v2
    description: "Web form for submitting new bug reports."
    config:
      title: "Report a Bug"
      schema: BugReport

  triage:
    type: triage_agent@v1
    description: "AI-powered risk classification of incoming bug reports."
    config:
      pipeline: triage_v2
      model: gpt-4o
    retry:
      max_attempts: 3
      backoff: exponential
      initial_delay: 5s

  approval:
    type: slack_approval@v1
    description: "Engineering lead sign-off for high-risk bugs."
    config:
      channel: "#ops-approvals"
      buttons: [Approve, Reject]
      timeout: 48h
    on_timeout:
      out:
        approved: false
        reason: "Auto-rejected: no response within 48 hours."

  gitlab:
    type: gitlab_issue_create@v1
    description: "Creates the canonical GitLab issue for the bug."
    config:
      project_id: "myorg/backend"
      default_labels: ["bug", "needs-triage"]

trigger: intake_form

edges:
  - from: intake_form
    to: triage
    with:
      title: trigger.in.title
      severity: trigger.in.severity
      description: trigger.in.description
      reporter_email: trigger.in.reporter_email

  - from: triage
    to: approval
    when: triage.out.risk == "high"
    with:
      title: "High-risk bug: {{triage.out.summary}}"
      risk_level: triage.out.risk
      reporter: trigger.in.reporter_email

  - from: triage
    to: gitlab
    when: triage.out.risk != "high"
    with:
      title: triage.out.summary
      labels: triage.out.labels
      assignee: triage.out.recommended_assignee

  - from: approval
    to: gitlab
    when: approval.out.approved == true
    with:
      title: triage.out.summary
      labels: triage.out.labels
      assignee: triage.out.recommended_assignee

output: gitlab.out.ticket_id

policy:
  audit:
    retain_run_logs_for: 365d
  pii_redaction:
    - node: triage
      redact_fields: [reporter_email]
```

---

## 17. Operational Packaging & Local Runtime (Implemented)

The current implementation supports two operational paths:

- `bpg up [process_file]` for local runtime startup.
- `bpg package [process_file]` for artifact generation and handoff.
- `bpg down [process_file]` for local runtime teardown.

### 17.1 Local Runtime (`bpg up`)

- If `process_file` is omitted, CLI defaults to `process.bpg.yaml` then `process.bpg.yml` in current directory.
- CLI auto-loads declarative provider registries from `bpg.providers.yaml` / `bpg.providers.yml` when present
  (or explicit `--providers-file`).
- Uses shared runtime inference with local defaults.
- Defaults ledger backend to `sqlite-file` unless overridden by policy tags.
- Builds local image `bpg-local:dev` from the current repository.
- Writes compose/runtime artifacts to `.bpg/local/<process_name>` (default).
- Runs services via `docker compose up -d`.
- Fails hard when required environment variables are unresolved.

### 17.2 Package Runtime (`bpg package`)

- If `process_file` is omitted, CLI defaults to `process.bpg.yaml` then `process.bpg.yml` in current directory.
- CLI auto-loads declarative provider registries from `bpg.providers.yaml` / `bpg.providers.yml` when present
  (or explicit `--providers-file`).
- Uses shared runtime inference with package defaults.
- Defaults ledger backend to `postgres` unless overridden by policy tags.
- Missing required environment variables are warning-only during packaging.
- Default package output is locally buildable and includes:
  - `docker-compose.yml`, `.env`, `.env.example`, `process.bpg.yaml`, `README.md`, `package-metadata.json`
  - Runtime build inputs: `Dockerfile`, `pyproject.toml`, `uv.lock`, and `src/**/*.py`
- Default run path is `docker compose up --build`.
- If `--image` or `BPG_PACKAGE_IMAGE` is set, package compose uses that explicit image instead of local-build mode.

### 17.3 Local Teardown (`bpg down`)

- `--local-dir` explicitly selects the compose runtime directory.
- Without `--local-dir`, CLI resolves local runtime dir from `process_file` metadata name:
  - explicit `process_file` argument, or
  - inferred default file (`process.bpg.yaml` then `process.bpg.yml`).
- If no process file is available, CLI falls back to legacy `.bpg/local/default` single-directory inference.

### 17.4 Dashboard Runtime

- `--dashboard` adds a dashboard service in local and package compose outputs.
- `--dashboard-port` configures host/container port mapping (default `8080`).

---

## 18. Search Pipelines Pattern (Implemented Baseline)

Search systems typically have two operational pipelines:

- ingestion (writes to index/vector stores)
- retrieval (reads from those stores)

The recommended BPG topology is two separate process graphs, not one merged graph:

- `search-ingest` process for file parsing/chunking/embedding/upsert
- `search-retrieve` process for query embedding and retrieval

### 18.1 Shared Datastore Contract

To ensure both processes target the same datastore, use a shared import with a typed store identifier and require every datastore node to declare it.

Example:

```yaml
types:
  SearchStoreRef:
    store: enum(search_main)
```

Node config then pins:

```yaml
config:
  store: search_main
```

Both processes MUST resolve `search_main` to the same runtime endpoint/collection via provider configuration and environment variables.

### 18.2 Built-in Search Nodes

The following node/provider pairs are implemented in the baseline runtime:

- `fs.markdown_list@v1` -> `fs.markdown_list`
- `text.markdown_chunk@v1` -> `text.markdown_chunk`
- `embed.text@v1` -> `embed.text`
- `weaviate.upsert@v1` -> `weaviate.upsert`
- `weaviate.hybrid_search@v1` -> `weaviate.hybrid_search`
- optional `weaviate.delete@v1` -> `weaviate.delete`

### 18.3 Weaviate-Specific Intent

The initial search contract targets Weaviate-style hybrid retrieval:

- BM25-like keyword retrieval
- vector similarity retrieval
- alpha-weighted fusion in `weaviate.hybrid_search`

### 18.4 Example Artifacts

Reference design graphs are provided under `examples/search/`:

- `search-resources.bpg.yaml` (shared contract)
- `ingest.bpg.yaml` (ingestion graph)
- `retrieve.bpg.yaml` (retrieval graph)

---

*End of Specification — BPG v0.2 Draft*
