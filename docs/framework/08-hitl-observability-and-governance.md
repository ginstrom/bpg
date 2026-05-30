# 08: HITL, Observability, and Governance

## Goal

Rebuild human approval, auditability, tracing, and governance features as Temporal-native framework behavior.

## Scope

- HITL semantics
- Audit trail
- Telemetry
- Policy enforcement

## Implementation

Approvals become framework-managed wait states driven by Temporal signals, queries, timers, and workflow state rather than ad hoc node logic. Define a stable actor identity model and approval audit payload schema so approvals, rejections, escalations, and timeouts are recorded consistently across all workflows.

Emit OpenTelemetry traces, metrics, and structured logs from Temporal workflows and activities. The framework should define field conventions for workflow IDs, node IDs, actor IDs, policy decisions, correlation IDs, and external side-effect references so operational data is consistent across packages.

Add governance hooks for required approvals, escalation rules, timeout behavior, and policy checks. The framework must be able to block or redirect execution based on those policies before risky actions occur. Dashboard and status APIs should be rebuilt against Temporal visibility plus the framework read model rather than the current append-only event log.

Use red/green TDD for implementation. When complete create a PR after ensuring
that all tests pass in accordance with @AGENTS.md

## Public Interfaces

- Approval signal and query contract
- Audit event schema
- Telemetry field conventions

## Test Plan

- Approval timeout and escalation tests
- Audit record completeness tests
- Trace and metric emission smoke tests
- Policy enforcement tests for approval-gated flows

## Acceptance Criteria

- Human approval and governance semantics are implemented by the framework on Temporal
- Audit and telemetry data are complete enough for operational review
- Enterprise guarantees do not depend on ad hoc package-specific logic

## Out of Scope

- Final dashboard UX design
- Vendor-specific observability backend configuration
- Custom compliance products beyond core framework hooks and schemas
