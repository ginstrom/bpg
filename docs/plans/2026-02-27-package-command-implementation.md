# Package Command Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement `bpg package` to generate an artifact-only Docker Compose deployment bundle for a process, with inferred internal services and warning-only unresolved env vars.

**Architecture:** Add a focused packaging layer under `bpg.packaging` with four concerns: spec modeling, service/env inference, artifact rendering, and output writing. Keep the CLI thin by delegating to a packaging orchestrator and returning a structured result that includes unresolved required vars and readiness state. Use TDD for each module, then add CLI coverage and manual documentation.

**Tech Stack:** Python 3.12, Typer CLI, PyYAML, pytest (`uv run pytest` from `.venv`).

---

### Task 1: Add Packaging Domain Models

**Files:**
- Create: `src/bpg/packaging/__init__.py`
- Create: `src/bpg/packaging/spec.py`
- Test: `tests/test_packaging_spec.py`

**Step 1: Write the failing tests for package spec dataclasses**

```python
from bpg.packaging.spec import EnvVarSpec, PackageResult


def test_env_var_spec_required_flag_and_default():
    spec = EnvVarSpec(name="DB_URL", required=True, value="postgres://x")
    assert spec.required is True
    assert spec.value == "postgres://x"


def test_package_result_ready_to_run_false_when_unresolved():
    result = PackageResult(unresolved_required_vars=["DB_URL"])
    assert result.ready_to_run is False
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_spec.py -v`
Expected: FAIL with import/module errors.

**Step 3: Write minimal implementation in `spec.py`**

```python
@dataclass(frozen=True)
class EnvVarSpec:
    name: str
    required: bool
    value: str | None = None
    description: str | None = None


@dataclass
class PackageResult:
    unresolved_required_vars: list[str] = field(default_factory=list)

    @property
    def ready_to_run(self) -> bool:
        return not self.unresolved_required_vars
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_spec.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_packaging_spec.py src/bpg/packaging/__init__.py src/bpg/packaging/spec.py
git commit -m "feat: add packaging domain models"
```

### Task 2: Implement Service and Env Inference

**Files:**
- Create: `src/bpg/packaging/inference.py`
- Modify: `src/bpg/providers/base.py`
- Test: `tests/test_packaging_inference.py`

**Step 1: Write failing inference tests**

```python
def test_infer_services_includes_postgres_for_postgres_ledger():
    spec = infer_package_spec(process=process_with_postgres_ledger())
    assert "postgres" in spec.services


def test_infer_services_excludes_postgres_for_sqlite_file_ledger():
    spec = infer_package_spec(process=process_with_sqlite_file_ledger())
    assert "postgres" not in spec.services


def test_infer_unresolved_required_var_marked_required():
    spec = infer_package_spec(process=process_with_required_env("API_KEY"), env={})
    required_names = [v.name for v in spec.env_vars if v.required]
    assert "API_KEY" in required_names
```

**Step 2: Run tests to verify failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_inference.py -v`
Expected: FAIL because inference functions/capabilities do not exist.

**Step 3: Add minimal provider capability contract + inference implementation**

```python
class Provider(ABC):
    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        return {"services": [], "required_env": []}
```

```python
def infer_package_spec(process, env: dict[str, str] | None = None) -> PackageSpec:
    ...
```

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_inference.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_packaging_inference.py src/bpg/packaging/inference.py src/bpg/providers/base.py
git commit -m "feat: infer package services and env requirements"
```

### Task 3: Render Deterministic Artifacts

**Files:**
- Create: `src/bpg/packaging/render.py`
- Test: `tests/test_packaging_render.py`

**Step 1: Write failing render tests**

```python
def test_render_env_uses_required_sentinel_for_missing_required():
    text = render_env([
        EnvVarSpec(name="API_KEY", required=True, value=None),
    ])
    assert "API_KEY=__REQUIRED__" in text


def test_render_compose_only_includes_inferred_services():
    compose = render_compose(spec_with_services(["postgres"]))
    assert "postgres:" in compose
    assert "redis:" not in compose
```

**Step 2: Run tests to verify failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_render.py -v`
Expected: FAIL because rendering functions are missing.

**Step 3: Implement minimal deterministic renderer**

```python
def render_env(env_vars: list[EnvVarSpec]) -> str:
    ...


def render_compose(spec: PackageSpec) -> str:
    ...
```

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_render.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_packaging_render.py src/bpg/packaging/render.py
git commit -m "feat: render deterministic package artifacts"
```

### Task 4: Add Writer With Safe Output Behavior

**Files:**
- Create: `src/bpg/packaging/writer.py`
- Test: `tests/test_packaging_writer.py`

**Step 1: Write failing writer tests**

```python
def test_write_package_fails_when_output_exists_without_force(tmp_path):
    out = tmp_path / "bundle"
    out.mkdir()
    with pytest.raises(FileExistsError):
        write_package(output_dir=out, files={"README.md": "x"}, force=False)


def test_write_package_overwrites_when_force_true(tmp_path):
    out = tmp_path / "bundle"
    out.mkdir()
    write_package(output_dir=out, files={"README.md": "new"}, force=True)
    assert (out / "README.md").read_text() == "new"
```

**Step 2: Run tests to verify failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_writer.py -v`
Expected: FAIL because writer does not exist.

**Step 3: Implement atomic temp-dir write and replace**

```python
def write_package(output_dir: Path, files: dict[str, str], force: bool) -> None:
    ...
```

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_writer.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_packaging_writer.py src/bpg/packaging/writer.py
git commit -m "feat: add package artifact writer with force semantics"
```

### Task 5: Wire `bpg package` Command

**Files:**
- Modify: `src/bpg/cli.py`
- Create: `tests/test_cli_package.py`
- Modify: `src/bpg/packaging/__init__.py`

**Step 1: Write failing CLI tests**

```python
def test_package_generates_expected_artifacts(tmp_path):
    result = runner.invoke(app, ["package", str(proc), "--output-dir", str(out)])
    assert result.exit_code == 0
    assert (out / "docker-compose.yml").exists()
    assert (out / ".env.example").exists()
    assert (out / ".env").exists()


def test_package_warns_on_unresolved_required_vars(tmp_path):
    result = runner.invoke(app, ["package", str(proc), "--output-dir", str(out)])
    assert result.exit_code == 0
    assert "unresolved required vars" in result.stdout.lower()
    assert "API_KEY=__REQUIRED__" in (out / ".env").read_text()
```

**Step 2: Run tests to verify failure**

Run: `source .venv/bin/activate && uv run pytest tests/test_cli_package.py -v`
Expected: FAIL because command does not exist.

**Step 3: Implement command + orchestration**

```python
@app.command()
def package(...):
    ...
```

- Parse + validate + compile process.
- Build package spec via inference.
- Render artifact files.
- Write output dir with `--force` semantics.
- Print warnings for unresolved required vars.

**Step 4: Run tests to verify pass**

Run: `source .venv/bin/activate && uv run pytest tests/test_cli_package.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add tests/test_cli_package.py src/bpg/cli.py src/bpg/packaging/__init__.py
git commit -m "feat: add bpg package command"
```

### Task 6: Documentation and Full Verification

**Files:**
- Modify: `manual/USER_MANUAL.md`
- Modify: `docs/bpg-spec.md` (only if command matrix should include package)

**Step 1: Write failing docs assertion test (optional if docs tests exist)**

If no docs tests exist, skip directly to Step 2.

**Step 2: Update docs for command contract and warning semantics**

Document:
- Artifact-only behavior
- `--output-dir`, `--force`
- `.env.example` vs `.env`
- `__REQUIRED__` sentinel
- inferred service inclusion behavior

**Step 3: Run targeted tests**

Run: `source .venv/bin/activate && uv run pytest tests/test_packaging_spec.py tests/test_packaging_inference.py tests/test_packaging_render.py tests/test_packaging_writer.py tests/test_cli_package.py -q`
Expected: PASS.

**Step 4: Run broader regression subset**

Run: `source .venv/bin/activate && uv run pytest tests/test_cli_plan.py tests/test_store.py tests/test_providers.py -q`
Expected: PASS.

**Step 5: Commit**

```bash
git add manual/USER_MANUAL.md docs/bpg-spec.md
git commit -m "docs: document package command and env semantics"
```

### Task 7: Final Validation and Handoff

**Files:**
- Modify: none expected

**Step 1: Run full suite (or agreed CI subset)**

Run: `source .venv/bin/activate && uv run pytest -q`
Expected: PASS (or capture known pre-existing failures separately).

**Step 2: Smoke-check generated package**

Run:
- `source .venv/bin/activate && uv run bpg package process.bpg.yaml --output-dir .bpg/package/sample --force`
- `ls -la .bpg/package/sample`

Expected:
- artifact set exists exactly as specified.
- warnings are printed when unresolved vars remain.

**Step 3: Prepare review**

```bash
git status --short
git log --oneline -n 8
```

Capture implemented scope and any follow-up items.

