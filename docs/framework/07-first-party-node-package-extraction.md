# 07: First-Party Node Package Extraction

## Goal

Remove runnable components from the core repo and ship them as first-party installable node packages.

## Scope

- Package split for current built-ins
- Framework examples updated to consume installed packages

## Implementation

Create the initial first-party node package set:

- `bpg-nodes-core`
- `bpg-nodes-ai`
- `bpg-nodes-human`
- `bpg-nodes-search`
- `bpg-nodes-comm`

Move current built-in runnable components into those packages and keep the framework repo focused on runtime, compiler, SDK, CLI, and related infrastructure. Move mock-only or test-only helpers into a dedicated test support package or fixture module so they do not remain mixed with production node code.

After the extracted packages are stable, remove built-in provider registration from the core framework. Example workflows should compile and run only against installed node packages, whether those packages come from the workspace during development or from published artifacts in external environments.

Add marketplace metadata generation for each first-party package so the framework and its official node packages share the same publishing contract.

## Public Interfaces

- Package names for the first-party node distributions
- Node IDs exposed by each package
- Install story based on `uv add`

## Test Plan

- Package install tests in clean virtualenvs
- Discovery tests across multiple installed node packages
- Example workflow compilation using only installed packages
- Marketplace metadata generation tests for each first-party package

## Acceptance Criteria

- The core repo no longer contains production runnable nodes
- First-party node packages install and register independently
- Examples rely on installed packages rather than in-repo built-ins

## Out of Scope

- Third-party package ecosystem design
- Long-term package taxonomy beyond the initial first-party split
- Preserving the current built-in provider registration model
