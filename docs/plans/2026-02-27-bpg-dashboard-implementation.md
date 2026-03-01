# BPG Dashboard Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a local/docker-runnable BPG dashboard (`--dashboard`) that shows graph, run/event state, and typed trigger input form.

**Architecture:** Extend runtime packaging spec with dashboard toggles, render dashboard compose service in local/package modes, add a FastAPI dashboard backend reading from `StateStore`, and serve a lightweight frontend that embeds existing graph HTML and consumes run/event APIs by polling.

**Tech Stack:** Python 3.12, Typer, FastAPI/Uvicorn, existing BPG state store, Docker Compose, pytest.

---

### Task 1: Extend Runtime Spec for Dashboard Options

**Files:**
- Modify: `src/bpg/packaging/runtime_spec.py`
- Modify: `src/bpg/packaging/inference.py`
- Test: `tests/test_runtime_spec.py`
- Test: `tests/test_runtime_inference.py`

**Step 1: Write failing tests for dashboard fields on runtime spec**
- Assert runtime spec has `dashboard_enabled` and `dashboard_port`.
- Assert defaults: disabled + port `8080`.

**Step 2: Run tests to verify failure**
Run: `uv run pytest tests/test_runtime_spec.py tests/test_runtime_inference.py -q`
Expected: FAIL due to missing fields.

**Step 3: Add fields and inference wiring**
- Extend `RuntimeSpec` model.
- Add parameters to `build_runtime_spec(..., dashboard=False, dashboard_port=8080)`.
- Propagate into inferred runtime spec.

**Step 4: Re-run tests**
Run: `uv run pytest tests/test_runtime_spec.py tests/test_runtime_inference.py -q`
Expected: PASS.

**Step 5: Commit**
`git commit -m "feat: add dashboard fields to runtime spec"`

### Task 2: Add CLI Flags for `package` and `up`

**Files:**
- Modify: `src/bpg/cli.py`
- Test: `tests/test_cli_package.py`
- Test: `tests/test_cli_runtime_orchestration.py`

**Step 1: Add failing CLI tests**
- `bpg package ... --dashboard` includes dashboard in generated compose.
- `bpg up ... --dashboard` includes dashboard service and port.

**Step 2: Run tests to verify failure**
Run: `uv run pytest tests/test_cli_package.py tests/test_cli_runtime_orchestration.py -q`
Expected: FAIL (unknown flags / missing compose service).

**Step 3: Implement CLI options**
- Add `--dashboard` bool and `--dashboard-port` int to `package` and `up`.
- Pass values into `build_runtime_spec`.

**Step 4: Re-run tests**
Run: `uv run pytest tests/test_cli_package.py tests/test_cli_runtime_orchestration.py -q`
Expected: PASS.

**Step 5: Commit**
`git commit -m "feat: add dashboard flags to package and up commands"`

### Task 3: Render Dashboard Compose Service

**Files:**
- Modify: `src/bpg/packaging/render.py`
- Modify: `src/bpg/packaging/inference.py` (metadata fields)
- Test: `tests/test_packaging_render.py`
- Test: `tests/test_cli_package.py`

**Step 1: Add failing render tests**
- With dashboard enabled, compose contains `dashboard` service.
- `dashboard` service includes state/process mounts and port binding.
- Metadata includes `dashboard_enabled`, `dashboard_port`.

**Step 2: Run tests to verify failure**
Run: `uv run pytest tests/test_packaging_render.py tests/test_cli_package.py -q`
Expected: FAIL due to missing service/metadata fields.

**Step 3: Implement compose + metadata rendering**
- Add dashboard service stanza.
- Keep deterministic ordering.
- Include metadata fields.

**Step 4: Re-run tests**
Run: `uv run pytest tests/test_packaging_render.py tests/test_cli_package.py -q`
Expected: PASS.

**Step 5: Commit**
`git commit -m "feat: render dashboard service in runtime bundles"`

### Task 4: Add Dashboard Backend API

**Files:**
- Create: `src/bpg/dashboard/__init__.py`
- Create: `src/bpg/dashboard/app.py`
- Create: `src/bpg/dashboard/schemas.py`
- Create: `tests/test_dashboard_api.py`

**Step 1: Write failing API tests**
- `GET /api/process` returns process + trigger schema.
- `GET /api/runs` returns latest runs.
- `GET /api/runs/{id}/events` returns event tail.
- `POST /api/trigger` creates run and returns `run_id`.

**Step 2: Run tests to verify failure**
Run: `uv run pytest tests/test_dashboard_api.py -q`
Expected: FAIL (module/app missing).

**Step 3: Implement FastAPI app**
- Build app with `StateStore` dependency from env `BPG_STATE_DIR`.
- Parse process from env `BPG_PROCESS_NAME` or request parameter.
- Add endpoints and response schemas.
- Add trigger validation against trigger input type.

**Step 4: Re-run tests**
Run: `uv run pytest tests/test_dashboard_api.py -q`
Expected: PASS.

**Step 5: Commit**
`git commit -m "feat: add dashboard backend API for state and trigger"`

### Task 5: Graph Reuse Endpoint

**Files:**
- Modify: `src/bpg/dashboard/app.py`
- Modify: `src/bpg/compiler/visualizer.py` (if helper extraction needed)
- Test: `tests/test_dashboard_api.py`

**Step 1: Add failing tests**
- `GET /api/graph` returns graph HTML payload for deployed process.
- Returned payload contains process title and graph root container.

**Step 2: Run tests to verify failure**
Run: `uv run pytest tests/test_dashboard_api.py -q`
Expected: FAIL on missing `/api/graph`.

**Step 3: Implement endpoint**
- Compile deployed process IR.
- Call existing `generate_html(ir)`.
- Return HTML string payload.

**Step 4: Re-run tests**
Run: `uv run pytest tests/test_dashboard_api.py -q`
Expected: PASS.

**Step 5: Commit**
`git commit -m "feat: expose graph HTML endpoint for dashboard"`

### Task 6: Add Dashboard Frontend Shell

**Files:**
- Create: `src/bpg/dashboard/static/index.html`
- Create: `src/bpg/dashboard/static/dashboard.js`
- Create: `src/bpg/dashboard/static/dashboard.css`
- Modify: `src/bpg/dashboard/app.py`
- Test: `tests/test_dashboard_ui_assets.py`

**Step 1: Add failing tests**
- Root route serves dashboard HTML.
- Frontend assets are served.
- HTML includes graph pane, runs pane, events pane, trigger form container.

**Step 2: Run tests to verify failure**
Run: `uv run pytest tests/test_dashboard_ui_assets.py -q`
Expected: FAIL due to missing static routes/assets.

**Step 3: Implement frontend shell**
- Serve static files from FastAPI.
- Build minimal UI with four panes.
- Poll APIs every 2 seconds for run/event updates.
- Embed graph via iframe or innerHTML from `/api/graph`.

**Step 4: Re-run tests**
Run: `uv run pytest tests/test_dashboard_ui_assets.py -q`
Expected: PASS.

**Step 5: Commit**
`git commit -m "feat: add dashboard frontend shell with graph and event panels"`

### Task 7: Trigger Form Auto-Generation

**Files:**
- Modify: `src/bpg/dashboard/static/dashboard.js`
- Modify: `src/bpg/dashboard/app.py` (schema endpoint shape)
- Test: `tests/test_dashboard_api.py`
- Test: `tests/test_dashboard_ui_assets.py`

**Step 1: Add failing tests**
- Trigger schema includes field metadata for UI rendering.
- UI builds form controls for `string/number/bool/enum/list`.
- Submitting form hits `/api/trigger` and refreshes run list.

**Step 2: Run tests to verify failure**
Run: `uv run pytest tests/test_dashboard_api.py tests/test_dashboard_ui_assets.py -q`
Expected: FAIL on missing schema/submit behavior.

**Step 3: Implement typed form generation**
- Build form model from trigger type fields.
- Parse/convert form values before submit.
- Display API validation errors inline.

**Step 4: Re-run tests**
Run: `uv run pytest tests/test_dashboard_api.py tests/test_dashboard_ui_assets.py -q`
Expected: PASS.

**Step 5: Commit**
`git commit -m "feat: add typed trigger form generation and submission"`

### Task 8: End-to-End Dashboard Integration

**Files:**
- Create: `tests/test_cli_dashboard_integration.py`
- Modify: `manual/USER_MANUAL.md`

**Step 1: Add failing integration tests**
- `bpg package --dashboard` emits runnable compose with dashboard service.
- `bpg up --dashboard` composes dashboard service and logs command includes dashboard.

**Step 2: Run tests to verify failure**
Run: `uv run pytest tests/test_cli_dashboard_integration.py -q`
Expected: FAIL until compose + CLI behavior is complete.

**Step 3: Implement and document final integration behavior**
- Ensure CLI output prints dashboard URL.
- Update manual with commands and env details.

**Step 4: Re-run integration tests**
Run: `uv run pytest tests/test_cli_dashboard_integration.py -q`
Expected: PASS.

**Step 5: Final verification sweep**
Run:
- `uv run pytest tests/test_dashboard_api.py tests/test_dashboard_ui_assets.py tests/test_cli_package.py tests/test_cli_runtime_orchestration.py tests/test_cli_dashboard_integration.py -q`
- `uv run pytest -q`
Expected: PASS.

**Step 6: Commit**
`git commit -m "feat: add dashboard mode for local and packaged runtimes"`

---

Plan complete and saved to `docs/plans/2026-02-27-bpg-dashboard-implementation.md`. Two execution options:

1. Subagent-Driven (this session) - I dispatch fresh subagent per task, review between tasks, fast iteration
2. Parallel Session (separate) - Open new session with executing-plans, batch execution with checkpoints

Which approach?
