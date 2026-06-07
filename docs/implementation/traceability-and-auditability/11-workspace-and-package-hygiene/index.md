# 11. Workspace and Package Hygiene

## Objective
Register `bpg-nodes-audit` in framework workspace expectations so CI and package-boundary checks pass after step 9.

## Rationale
Step 9 added `packages/bpg-nodes-audit` to the workspace, but framework layout tests and package ownership docs were not updated. The full test suite currently fails on:

- `tests/framework/test_workspace_layout.py::test_workspace_declares_expected_members`
- `tests/framework/test_workspace_layout.py::test_boundary_policy_covers_all_framework_packages`

## Primary Touchpoints
- `tests/framework/test_workspace_layout.py`
- `docs/reference/package_ownership.md`
- `packages/package-boundaries.toml` (already has `bpg_nodes_audit`; verify only)
- `pyproject.toml` workspace members (already present; verify only)

## Scope

### In scope
- Add `packages/bpg-nodes-audit` to `EXPECTED_WORKSPACE_MEMBERS`.
- Add `packages/bpg-nodes-audit: bpg_nodes_audit` to `EXPECTED_IMPORT_ROOTS`.
- Document `bpg_nodes_audit` in `docs/reference/package_ownership.md`.
- Confirm `test_first_party_nodes.py` expectations remain aligned (already updated in step 9).

### Out of scope
- New audit node functionality.
- Changing package boundary import rules unless required by test failures.

## Implementation Tasks

1. Update `EXPECTED_WORKSPACE_MEMBERS` and `EXPECTED_IMPORT_ROOTS` in `test_workspace_layout.py`.

2. Add a `bpg_nodes_audit` section to `package_ownership.md` consistent with other `bpg-nodes-*` packages.

3. Run framework layout and first-party node discovery tests.

4. Run `uv sync` smoke path in `test_uv_workspace_sync_smoke` to ensure imports resolve.

## Acceptance Criteria
- `uv run pytest tests/framework/test_workspace_layout.py` passes.
- `uv run pytest tests/framework/test_first_party_nodes.py` passes.
- `bpg_nodes_audit` appears in package ownership documentation.
- Full `uv run pytest` no longer fails on workspace layout assertions.

## Verification

```bash
uv run pytest tests/framework/test_workspace_layout.py tests/framework/test_first_party_nodes.py
uv run pytest
```

## Dependencies
- None. Can land independently and should land early to restore CI green.
