# Release and Versioning Rules

## Overview

The BPG workspace ships two categories of packages that evolve together but
follow different compatibility guarantees:

- **Framework packages** (`bpg-core`, `bpg-sdk`, `bpg-temporal`, `bpg-langgraph`, `bpg-cli`)
  form the stable authoring and runtime API surface.
- **First-party node packages** (`bpg-nodes-core`, `bpg-nodes-ai`, `bpg-nodes-human`,
  `bpg-nodes-search`, `bpg-nodes-comm`) are installable node distributions that
  implement the SDK authoring contract.

## Version Alignment

All packages in the workspace share a single version number at release time.
The root `pyproject.toml` version is the authoritative source; all workspace
packages must match it before a release is cut.

## First Release: 0.1.0

The `0.1.0` release includes:

- All framework packages at `0.1.0`.
- All first-party node packages at `0.1.0`.
- The `bpg` CLI command from `bpg-cli`.
- Entry-point discovery via the `bpg.nodes` group (PEP 517).

This is a clean-break release. No compatibility guarantees are made with any
pre-framework code or schemas.

## Compatibility Rules

### Framework packages

| Change type | Version bump |
|-------------|-------------|
| New public API | minor (0.1.x → 0.2.0) |
| Breaking API change | major (0.x.y → 1.0.0) |
| Bug fix / internal | patch (0.1.0 → 0.1.1) |

### Node packages

Node packages use the `@vN` suffix in their `package` field (e.g. `bpg.nodes.core@v1`).
The PyPI version and the `@vN` suffix evolve independently:

- Incrementing `@vN` (e.g. `@v1` → `@v2`) signals a breaking change to the
  node's input/output schema and requires a major PyPI version bump.
- New nodes added to an existing `@vN` package are non-breaking and require
  only a minor version bump.
- Bug fixes within a stable schema require only a patch bump.

## Release Checklist

1. Bump the version in the root `pyproject.toml`.
2. Run `uv sync` to propagate the version to all workspace packages.
3. Verify version alignment: `uv run python -m pytest tests/framework/test_publishing_dry_run.py -k version`.
4. Build all packages: `uv build --all-packages`.
5. Run the full test suite: `uv run python -m pytest`.
6. Tag the release: `git tag v0.1.0`.
7. Publish: `uv publish --all-packages`.

## Node Package Lifecycle

Node packages are registered in `bpg-marketplace` after publishing. The
marketplace sync command (`bpg marketplace sync`) is used to update the registry.

Framework packages and node packages are versioned together at `0.1.0` but may
diverge in patch and minor releases as they mature independently.
