# 05: Node SDK and Discovery

## Goal

Replace the current provider abstraction with a framework SDK for authoring and discovering installable node packages.

## Scope

- Node authoring APIs
- Metadata schema
- Entry-point-based discovery

## Implementation

Add a `bpg-sdk` package that provides two primary authoring paths:

- a `@node` decorator for simple function nodes
- a class-based `Node` API for advanced nodes

Define required metadata for every node:

- input schema
- output schema
- capabilities
- side effects
- idempotency
- retry safety
- observability support

Use Python entry points under a single group such as `bpg.nodes` so installed packages can register nodes without modifying framework code. The discovery system loads installed entry points, validates their manifests, and exposes the resulting node catalog to the compiler, CLI, and runtime bootstrap.

Provide SDK helpers for Temporal activity registration and optional LangGraph behavior registration so package authors can express advanced execution behavior without reimplementing framework plumbing.

The framework-generated node manifest becomes the canonical metadata format consumed by both the compiler and the marketplace exporter.

## Public Interfaces

- `bpg-sdk` authoring API
- Entry-point registration contract
- Generated node manifest format

## Test Plan

- Sample package discovery tests
- Metadata validation tests
- Authoring smoke tests for function and class nodes
- Entry-point resolution tests in a clean virtualenv managed with `uv`

## Acceptance Criteria

- Nodes can be installed independently
- Installed nodes are discovered automatically through entry points
- Workflows compile against discovered nodes without touching core framework code

## Out of Scope

- Compatibility with the current provider inheritance model
- Marketplace publishing automation beyond manifest generation requirements
- Non-Python discovery mechanisms
