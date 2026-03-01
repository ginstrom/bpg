# Runtime/Package Parity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `bpg package` and local runtime startup use the same inferred runtime model so both paths produce a usable, runnable system for a specific business process.

**Architecture:** Introduce a shared runtime specification pipeline (`RuntimeSpec`) consumed by both artifact generation (`bpg package`) and local orchestration (`bpg up/down/logs`). Keep packaging artifact-only while adding explicit local lifecycle commands that perform readiness checks, bootstrap steps, and fail-fast validation for unresolved required variables.

**Tech Stack:** Python 3.12, Typer CLI, PyYAML, Docker Compose CLI integration, pytest (`uv run pytest` from `.venv`).

---

### Task 1: Define Shared RuntimeSpec Model

**Files:**
- Create: `src/bpg/packaging/runtime_spec.py`
- Modify: `src/bpg/packaging/spec.py`
- Test: `tests/test_runtime_spec.py`

**Step 1: Write failing tests for RuntimeSpec shape**

```python
from bpg.packaging.runtime_spec import RuntimeSpec


def test_runtime_spec_tracks_services_env_and_readiness_requirements():
    spec = RuntimeSpec(
        process_name="p1",
        services=["postgres"],
        required_env=["API_KEY"],
        unresolved_required_env=["API_KEY"],
    )
    assert spec.process_name == "p1"
    assert "postgres" in spec.services
    assert spec.ready_to_run is False
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && uv run pytest tests/test_runtime_spec.py -v`
Expected: FAIL with import errors.

**Step 3: Implement minimal RuntimeSpec dataclass**

```python
@dataclass
class RuntimeSpec:
    ...

    @property
    def ready_to_run(self) -> bool:
        return len(self.unresolved_required_env) == 0
```

**Step 4: Run test to verify pass**

Run: `source .venv/bin/activate && uv run pytest tests/test_runtime_spec.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/packaging/runtime_spec.py src/bpg/packaging/spec.py tests/test_runtime_spec.py
git commit -m "feat: add shared runtime spec model"
```

### Task 2: Refactor Inference to Build RuntimeSpec Once

**Files:**
- Modify: `src/bpg/packaging/inference.py`
- Modify: `src/bpg/providers/base.py`
- Modify: `src/bpg/providers/builtin.py`
- Test: `tests/test_packaging_inference.py`
- Test: `tests/test_runtime_inference.py`

**Step 1: Write failing tests for parity inference**

```python
def test_build_runtime_spec_for_package_defaults_postgres():
    spec = build_runtime_spec(process, mode="package", env={})
    assert "postgres" in spec.services


def test_build_runtime_spec_for_local_defaults_sqlite_file():
    spec = build_runtime_spec(process, mode="local", env={})
    assert "postgres" not in spec.services


def test_provider_requirements_are_merged_into_runtime_spec():
    spec = build_runtime_spec(process_with_provider_requirement("redis"), mode="package", env={})
    assert "redis" in spec.services
```

**Step 2: Run tests to verify failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_inference.py tests/test_runtime_inference.py -v`
Expected: FAIL due to missing `build_runtime_spec` and mode behavior.

**Step 3: Implement unified inference entrypoint**

```python
def build_runtime_spec(process, process_file_text: str, mode: Literal["local", "package"], env: dict[str, str] | None = None) -> RuntimeSpec:
    ...
```

- `mode="package"`: default ledger backend postgres.
- `mode="local"`: default ledger backend sqlite-file.
- Respect explicit process override (`policy.audit.tags.ledger_backend`) in both modes.
- Merge provider service/env requirements through `packaging_requirements`.

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_inference.py tests/test_runtime_inference.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/packaging/inference.py src/bpg/providers/base.py src/bpg/providers/builtin.py tests/test_packaging_inference.py tests/test_runtime_inference.py
git commit -m "feat: unify runtime inference for local and package modes"
```

### Task 3: Make Package Rendering Consume RuntimeSpec

**Files:**
- Modify: `src/bpg/packaging/render.py`
- Modify: `src/bpg/packaging/__init__.py`
- Test: `tests/test_packaging_render.py`
- Test: `tests/test_cli_package.py`

**Step 1: Write failing tests for RuntimeSpec-driven rendering**

```python
def test_render_compose_uses_runtime_spec_services():
    runtime_spec = runtime_spec_with_services(["postgres", "redis"])
    compose = render_compose(runtime_spec)
    assert "postgres:" in compose
    assert "redis:" in compose


def test_package_metadata_contains_ready_to_run_from_runtime_spec():
    metadata = render_metadata(runtime_spec_with_unresolved(["API_KEY"]))
    assert '"ready_to_run": false' in metadata
```

**Step 2: Run tests to verify failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_render.py tests/test_cli_package.py -v`
Expected: FAIL on signature/behavior mismatch.

**Step 3: Update render functions to accept RuntimeSpec**

```python
def render_compose(runtime_spec: RuntimeSpec) -> str:
    ...
```

- Keep deterministic ordering and generated file set unchanged.
- Preserve `.env` unresolved sentinel `__REQUIRED__`.

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_render.py tests/test_cli_package.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/packaging/render.py src/bpg/packaging/__init__.py tests/test_packaging_render.py tests/test_cli_package.py
git commit -m "refactor: render package artifacts from shared runtime spec"
```

### Task 4: Add Local Orchestration Commands (`up`, `down`, `logs`)

**Files:**
- Modify: `src/bpg/cli.py`
- Create: `src/bpg/runtime/orchestration.py`
- Test: `tests/test_cli_runtime_orchestration.py`

**Step 1: Write failing CLI tests for local lifecycle**

```python
def test_up_fails_when_unresolved_required_vars(tmp_path):
    result = runner.invoke(app, ["up", str(proc), "--local-dir", str(tmp_path / "run")])
    assert result.exit_code == 1
    assert "unresolved required vars" in result.stdout.lower()


def test_up_generates_local_runtime_bundle_and_invokes_compose(tmp_path, monkeypatch):
    result = runner.invoke(app, ["up", str(proc), "--local-dir", str(tmp_path / "run")])
    assert result.exit_code == 0
    assert (tmp_path / "run" / "docker-compose.yml").exists()
```

**Step 2: Run tests to verify failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_cli_runtime_orchestration.py -v`
Expected: FAIL because commands do not exist.

**Step 3: Implement orchestration abstraction and CLI commands**

- Add commands:
  - `bpg up <process-file> [--local-dir DIR] [--force]`
  - `bpg down [--local-dir DIR]`
  - `bpg logs [--local-dir DIR] [--service SERVICE]`
- `up` flow:
  1. parse/validate/compile
  2. build `RuntimeSpec(mode="local")`
  3. write local compose/env bundle
  4. fail hard if unresolved required vars remain
  5. run `docker compose up -d`
- `down` and `logs` use same local-dir compose context.

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && uv run pytest tests/test_cli_runtime_orchestration.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/cli.py src/bpg/runtime/orchestration.py tests/test_cli_runtime_orchestration.py
git commit -m "feat: add local runtime lifecycle commands"
```

### Task 5: Add Readiness and Bootstrap Checks

**Files:**
- Modify: `src/bpg/runtime/orchestration.py`
- Modify: `src/bpg/state/store.py` (only if needed for bootstrap hooks)
- Test: `tests/test_runtime_readiness.py`

**Step 1: Write failing readiness tests**

```python
def test_readiness_reports_missing_database_when_postgres_required():
    report = check_runtime_readiness(runtime_spec_with_postgres(), services_state={"postgres": "down"})
    assert report.ready is False
    assert "postgres" in " ".join(report.errors).lower()


def test_readiness_passes_when_all_dependencies_ready():
    report = check_runtime_readiness(runtime_spec_with_postgres(), services_state={"postgres": "healthy"})
    assert report.ready is True
```

**Step 2: Run tests to verify failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_runtime_readiness.py -v`
Expected: FAIL because readiness checker is missing.

**Step 3: Implement readiness checker + bootstrap hook framework**

```python
def check_runtime_readiness(runtime_spec: RuntimeSpec, ...) -> ReadinessReport:
    ...
```

- Validate unresolved required env vars.
- Validate inferred core services are up/healthy.
- Add bootstrap stage placeholder (migrations/schema/apply process).

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && uv run pytest tests/test_runtime_readiness.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/runtime/orchestration.py src/bpg/state/store.py tests/test_runtime_readiness.py
git commit -m "feat: add runtime readiness and bootstrap checks"
```

### Task 6: Update `package` and Local UX Messaging

**Files:**
- Modify: `src/bpg/cli.py`
- Test: `tests/test_cli_package.py`
- Test: `tests/test_cli_runtime_orchestration.py`

**Step 1: Write failing UX tests**

```python
def test_package_warns_but_succeeds_on_unresolved_vars():
    result = runner.invoke(app, ["package", ...])
    assert result.exit_code == 0
    assert "unresolved required vars" in result.stdout.lower()


def test_up_fails_with_actionable_message_on_unresolved_vars():
    result = runner.invoke(app, ["up", ...])
    assert result.exit_code == 1
    assert "set the following vars" in result.stdout.lower()
```

**Step 2: Run tests to verify failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_cli_package.py tests/test_cli_runtime_orchestration.py -v`
Expected: FAIL if messages/exit behavior not aligned.

**Step 3: Align command semantics**

- `package`: warning-only unresolved vars.
- `up`: fail hard on unresolved required vars before compose up.
- Ensure both print exact unresolved var list and sources.

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && uv run pytest tests/test_cli_package.py tests/test_cli_runtime_orchestration.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/cli.py tests/test_cli_package.py tests/test_cli_runtime_orchestration.py
git commit -m "refactor: align package and local runtime validation UX"
```

### Task 7: Documentation for Operator Workflows

**Files:**
- Modify: `manual/USER_MANUAL.md`
- Modify: `docs/bpg-spec.md`
- Create: `docs/plans/2026-02-27-runtime-package-parity-design-notes.md` (optional capture)

**Step 1: Update docs for two lifecycle paths**

Document:
- Local lifecycle (`bpg up/down/logs`).
- Artifact lifecycle (`bpg package`).
- Parity guarantee and known differences.
- Env behavior (`__REQUIRED__`, warning vs hard fail).

**Step 2: Run docs consistency check (if any)**

If no docs tooling exists, skip.

**Step 3: Commit docs**

```bash
git add manual/USER_MANUAL.md docs/bpg-spec.md docs/plans/2026-02-27-runtime-package-parity-design-notes.md
git commit -m "docs: describe local and packaged runtime lifecycle"
```

### Task 8: Verification Before Completion

**Files:**
- Modify: none expected

**Step 1: Run targeted new test suite**

Run:
`source .venv/bin/activate && uv run pytest tests/test_runtime_spec.py tests/test_runtime_inference.py tests/test_packaging_inference.py tests/test_packaging_render.py tests/test_cli_package.py tests/test_cli_runtime_orchestration.py tests/test_runtime_readiness.py -q`

Expected: PASS.

**Step 2: Run regression subset**

Run:
`source .venv/bin/activate && uv run pytest tests/test_cli_plan.py tests/test_store.py tests/test_providers.py tests/test_langgraph_runtime.py -q`

Expected: PASS (or pre-existing failures documented).

**Step 3: Smoke-check both workflows**

Run:
- `source .venv/bin/activate && uv run bpg package process.bpg.yaml --output-dir .bpg/package/parity --force`
- `source .venv/bin/activate && uv run bpg up process.bpg.yaml --local-dir .bpg/local/parity --force`
- `source .venv/bin/activate && uv run bpg logs --local-dir .bpg/local/parity`
- `source .venv/bin/activate && uv run bpg down --local-dir .bpg/local/parity`

Expected:
- package artifacts created
- local runtime starts/stops cleanly
- readiness and unresolved var behavior matches design

**Step 4: Final review prep**

Run:
- `git status --short`
- `git log --oneline -n 12`

Capture scope, open risks, and follow-up items.

