# 02: Process Spec and Compiler V2

## Goal

Redesign the process spec so workflows reference discoverable node packages and framework-owned semantics instead of raw provider bindings.

## Scope

- Replace provider-centric node typing with package and node identifiers
- Define framework-owned semantics for retries, timeouts, compensation, approvals, and observability

## Implementation

Introduce a v2 spec built around framework-controlled objects:

- `ProcessSpec`
- `NodeRef`
- `EdgeSpec`
- `RetryPolicy`
- `ApprovalPolicy`
- `CompensationPolicy`

User-authored workflow specs stop referencing provider classes or `PROVIDER_REGISTRY` identifiers directly. Instead, each node references an installed node package and exported node ID. The compiler resolves those node references through package discovery and compiles a framework IR that is ready for Temporal execution planning.

The compiler should emit two major outputs:

- a Temporal-ready execution plan
- a node capability requirements summary used by runtime bootstrapping and policy checks

Framework semantics such as retries, timeout handling, compensation strategy, human approvals, and observability requirements must be declared in spec v2 and represented explicitly in compiler IR. These are no longer accidental properties of whichever provider implementation happens to execute a node.

Define a stable node package identifier format such as `bpg.nodes.slack.approval@v1`. The versioned identifier belongs to the node package contract and remains stable across compiler, runtime, CLI, and marketplace flows.

## Public Interfaces

- New YAML schema for process spec v2
- Canonical IR types used by the compiler and runtime handoff
- Stable node package identifier format

## Test Plan

- Parse, validate, and compiler tests for valid and invalid v2 specs
- Fixture coverage for retries, branch conditions, approvals, and child workflows
- Compiler tests verifying node capability requirements output

## Acceptance Criteria

- Spec v2 expresses all framework semantics without referencing internal provider classes
- Installed node package identifiers replace provider IDs in user-authored workflow specs
- Compiler output is suitable for direct Temporal execution planning

## Out of Scope

- Compatibility shims for the current YAML schema
- Preserving `PROVIDER_REGISTRY` as a long-term authoring concept
- Runtime execution changes beyond what is needed to define the compiler contract
