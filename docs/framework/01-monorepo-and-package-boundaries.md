# 01: Monorepo and Package Boundaries

Status: Done

## Goal

Convert the repo from a single package with mixed responsibilities into a `uv` workspace with explicit framework package ownership.

## Scope

- Add a workspace layout under `packages/`
- Move current code into package-aligned modules
- Delete the old runtime and backend split once the new package skeleton is in place

## Implementation

Create a workspace rooted at the repo `pyproject.toml` and manage it with `uv`. The initial framework package set is:

- `packages/bpg-core`
- `packages/bpg-sdk`
- `packages/bpg-temporal`
- `packages/bpg-langgraph`
- `packages/bpg-cli`

Restructure source ownership so the compiler, schema, and framework-owned semantics live in `bpg-core`; the CLI moves into `bpg-cli`; Temporal runtime code lives in `bpg-temporal`; and LangGraph-specific node execution support lives in `bpg-langgraph`.

Keep test structure split by package, with cross-package and end-to-end coverage remaining at the repo root. During the transition, mark current `src/bpg/providers/` and `src/bpg/runtime/engine.py` as legacy inputs scheduled for removal by later PRs instead of treating them as long-term package boundaries.

Add import boundary checks so package internals do not freely reach across ownership lines. The purpose of this PR is not a full semantic rewrite. It is to establish the workspace skeleton and make later PRs land against stable package roots.

## Public Interfaces

- Root workspace `pyproject.toml` using `uv`
- Package import roots for `bpg_core`, `bpg_sdk`, `bpg_temporal`, `bpg_langgraph`, and `bpg_cli`
- Documented ownership rules for which package owns compiler APIs, runtime APIs, and authoring APIs

## Test Plan

- Create a fresh virtualenv with `uv venv`
- Install and sync the workspace with `uv sync`
- Run package import smoke tests from the virtualenv
- Run a CLI entrypoint smoke test from the virtualenv

## Acceptance Criteria

- The repo installs as a `uv` workspace inside a virtualenv
- Framework package boundaries are documented
- Imports and tests enforce the intended package ownership model

## Out of Scope

- Backward compatibility with the current single-package layout
- Final removal of all legacy runtime and provider code
- Semantic redesign of the process spec or runtime behavior
