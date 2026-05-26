# 03: Temporal Runtime Foundation

## Goal

Make Temporal the only runtime engine and move execution durability into Temporal workflows and activities.

## Scope

- Replace the current engine, backend, and orchestrator execution loop
- Define the Temporal workflow model, activity model, and persistence model

## Implementation

Add `BpgWorkflow` as the top-level Temporal workflow for each process run. That workflow becomes the source of truth for run lifecycle, state transitions, retries, pause and resume behavior, cancellations, and other framework semantics.

Ordinary node work executes as Temporal activities. Long-running framework coordination stays inside workflow state and uses Temporal signals, queries, timers, and child workflows. The current local and LangGraph backend split is retired. BPG becomes a single-runtime system whose durable behavior is owned by Temporal.

Store run identity, status, lineage, and searchable metadata in Temporal visibility and search attributes. If the framework keeps a separate read model for dashboards or reporting, that read model exists for query ergonomics only and never replaces Temporal as the operational source of truth.

Define a bootstrap layer named `TemporalRuntime` responsible for worker registration, workflow registration, activity registration, namespace configuration, codecs, and operational runtime settings.

## Public Interfaces

- `TemporalRuntime` bootstrap and worker registration API
- Workflow input and output payload contract
- Signal and query names for pause, resume, cancel, approval response, and status inspection

## Test Plan

- Local Temporal integration tests run from a virtualenv using `uv`
- Retry and idempotency tests
- Pause, resume, and cancellation tests
- Visibility and search attribute smoke tests

## Acceptance Criteria

- A v2 process spec runs end to end on Temporal
- The current local and LangGraph backend system is no longer required for framework execution
- Temporal is the durable source of truth for run state

## Out of Scope

- Non-Temporal runtime targets
- Final dashboard or reporting product design
- Node authoring APIs beyond what is needed to execute installed nodes
