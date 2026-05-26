# Framework Package Ownership

This workspace split establishes stable package roots without forcing an immediate semantic rewrite of the existing `bpg` package.

## Package Roots

- `bpg_core` owns compiler APIs, schema-facing validation, and framework semantics.
- `bpg_sdk` owns author-facing SDK interfaces such as provider contracts and execution context types.
- `bpg_temporal` is reserved for Temporal runtime integration and currently exposes only transitional placeholders.
- `bpg_langgraph` owns LangGraph-specific runtime execution support.
- `bpg_cli` owns CLI entrypoints and command composition.

## Transition Policy

The current `bpg` package remains installed during this transition as a legacy bridge. The new workspace packages may re-export from `bpg` until later framework PRs move implementations behind their final package roots.

Cross-package imports are intentionally constrained. The machine-readable policy lives in `packages/package-boundaries.toml`, and tests enforce those declared boundaries so later PRs land against stable ownership lines instead of ad hoc imports.
