# 09: CLI, Examples, and Release Cutover

## Goal

Finish the framework by replacing the developer workflow, examples, and release process around the new architecture.

## Scope

- CLI redesign
- Examples and templates refresh
- First release plan

## Implementation

Replace old runtime and package commands with framework commands for initialization, validation, compilation, worker startup, testing, execution support, and marketplace export. The CLI should reflect the new architecture directly rather than exposing obsolete provider or backend concepts.

Add example apps that install node packages from the workspace during development or from package indexes in published usage. Refresh templates so new users see package-based node discovery, Temporal worker startup, and LangGraph-enabled node behavior from the beginning.

Document local Temporal development, worker startup, and framework flows using a virtualenv plus `uv`. The release cutover for `0.1.0` should include the framework workspace packages and the corresponding first-party node packages, along with clear versioning rules for how framework packages and node packages evolve together.

## Public Interfaces

- Final CLI command set
- Example project layout
- Release and versioning rules between framework packages and node packages

## Test Plan

- End-to-end example tests against local Temporal
- CLI golden tests
- Package publishing dry runs
- New-user setup smoke test in a clean virtualenv using `uv`

## Acceptance Criteria

- A new user can install the framework, install node packages, run a Temporal worker, execute an example workflow, and discover packages via marketplace metadata
- CLI and examples no longer depend on the old provider and backend model
- The repository is ready to cut the first framework release

## Out of Scope

- Backward-compatible support for legacy CLI commands
- Long-term release automation beyond the initial cutover
- Non-Temporal examples
