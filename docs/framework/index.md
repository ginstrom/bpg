# Framework Roadmap

## Overview

This roadmap defines the target state for BPG as a framework-first system built around durable execution, installable node packages, and explicit package boundaries.

The design assumes:

- Temporal is the only runtime target.
- This is a clean-break framework redesign, not a compatibility migration.
- LangGraph is used only for LLM and agent behavior inside BPG nodes, not as the top-level workflow scheduler.
- Runnable components move out of the core repo into installable node packages and are then registered in `bpg-marketplace`.
- The repo becomes a `uv`-managed Python workspace, and all Python commands and tests run inside a virtualenv.

## Target Package Model

- `bpg-core`: process spec, compiler, framework IR, validation, and shared semantics
- `bpg-sdk`: node authoring APIs, metadata models, and discovery helpers
- `bpg-temporal`: Temporal runtime bootstrap, workflows, activities, and operational integration
- `bpg-langgraph`: LangGraph behavior contract and durable node-level execution support
- `bpg-cli`: framework CLI commands for authoring, validation, runtime operations, and marketplace automation
- first-party node packages: installable node distributions published independently from the framework packages

Marketplace artifacts are metadata plus installable package references, matching the marketplace design rather than hosting runnable code directly inside the registry.

## Implementation Sequence

1. [01-monorepo-and-package-boundaries.md](01-monorepo-and-package-boundaries.md): Split the repo into explicit framework packages and freeze ownership boundaries.
2. [x] [02-process-spec-and-compiler-v2.md](02-process-spec-and-compiler-v2.md): Replace the current provider-centric spec with a node-package-centric framework spec.
3. [03-temporal-runtime-foundation.md](03-temporal-runtime-foundation.md): Make Temporal the only execution runtime and move run semantics into Temporal workflows and activities.
4. [04-langgraph-llm-runtime.md](04-langgraph-llm-runtime.md): Add a durable LangGraph execution model for LLM and agent nodes under Temporal.
5. [05-node-sdk-and-discovery.md](05-node-sdk-and-discovery.md): Introduce the authoring SDK, node metadata contract, and Python entry-point discovery.
6. [06-marketplace-publishing-contract.md](06-marketplace-publishing-contract.md): Define marketplace metadata generation, validation, and publish and sync automation.
7. [07-first-party-node-package-extraction.md](07-first-party-node-package-extraction.md): Extract built-in runnable components into installable first-party node packages.
8. [08-hitl-observability-and-governance.md](08-hitl-observability-and-governance.md): Rebuild approvals, audit, tracing, and operational controls on Temporal.
9. [09-cli-examples-and-release-cutover.md](09-cli-examples-and-release-cutover.md): Replace the CLI and dev flows, refresh examples, and cut the first framework release.
