# 04: LangGraph LLM Runtime

## Goal

Use LangGraph as the execution engine for LLM behavior while keeping Temporal in control of durability and orchestration.

## Scope

- Define the runtime contract for LLM and agent nodes
- Make LangGraph runs resumable under Temporal

## Implementation

Introduce a `LangGraphNodeWorkflow` child workflow for nodes that declare `engine: langgraph`. Temporal still owns orchestration, retry boundaries, and recovery behavior. LangGraph is only responsible for node-local agent behavior inside the child workflow contract.

Model calls, tool calls, and other external side effects must execute as Temporal activities invoked from the child workflow. This prevents Temporal replay from implicitly re-running nondeterministic work. The child workflow maintains deterministic orchestration state while side effects stay behind activity boundaries.

Checkpoint LangGraph state at node-step boundaries using Temporal workflow state and optional blob storage for large payloads. The checkpoint contract should make restart and resume behavior explicit. Large conversation state, tool traces, or intermediate artifacts can spill to object storage when they exceed practical workflow payload limits.

Define deterministic replay boundaries clearly:

- workflow code may reconstruct control state from checkpoints
- workflow replay must not repeat model or tool side effects
- retries occur at explicit activity boundaries or explicit child workflow restart points

## Public Interfaces

- `LangGraphBehavior` contract in `bpg-langgraph`
- Node metadata fields for graph engine, checkpoint policy, tool registry, and structured output schema

## Test Plan

- LLM node happy-path tests
- Resume-after-worker-restart tests
- Tool failure and retry tests
- Large-state checkpoint tests

## Acceptance Criteria

- LangGraph-backed nodes are durable under Temporal
- LangGraph acts as a node-level execution engine, not a workflow-level scheduler
- Replay boundaries prevent implicit re-execution of nondeterministic model and tool logic

## Out of Scope

- Using LangGraph as the top-level workflow scheduler
- Supporting non-Temporal durability for agent nodes
- General-purpose agent abstractions outside node execution contracts
