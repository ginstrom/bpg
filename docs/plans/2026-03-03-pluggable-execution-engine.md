# Pluggable Execution Engine Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make LangGraph pluggable as a BPG execution backend by introducing a runtime engine adapter boundary and enabling at least one alternate backend selection path.

**Architecture:** Keep BPG semantics/state ownership in `runtime/engine.py` and move backend-specific execution behind a small adapter/registry API. Implement `langgraph` as the default backend and add a lightweight `local` backend to prove backend swapping with unchanged process semantics for simple flows.

**Tech Stack:** Python 3.12, Typer CLI, existing BPG compiler/runtime/state store, pytest, uv.

---

### Task 1: Introduce Runtime/Engine Boundary Types

**Files:**
- Create: `src/bpg/runtime/backends.py`
- Modify: `src/bpg/runtime/__init__.py`
- Test: `tests/test_engine_backends.py`

**Step 1: Write failing tests for backend registry contract**
- Verify unknown backend fails with clear message.
- Verify `langgraph` backend resolves.

**Step 2: Add backend-neutral contracts**
- Define `ExecutionBackend` protocol with `run(...) -> dict[str, Any]`.
- Define `ExecutionBackendFactory` protocol and `get_backend(name)` registry.

**Step 3: Add initial backend registry implementation**
- Register `langgraph` and `local` names.

**Step 4: Run tests**
- `uv run pytest -q tests/test_engine_backends.py`

**Step 5: Commit**
- Commit boundary+tests.

### Task 2: Implement LangGraph Backend Adapter

**Files:**
- Create: `src/bpg/engines/langgraph/backend.py`
- Create: `src/bpg/engines/langgraph/__init__.py`
- Modify: `src/bpg/runtime/engine.py`
- Test: `tests/test_engine.py`

**Step 1: Write failing test for Engine using backend adapter**
- Assert `Engine(..., backend="langgraph")` still runs an existing process.

**Step 2: Add adapter implementation**
- Move LangGraph runtime invocation behind adapter class.

**Step 3: Wire Engine to backend selection**
- Default backend remains `langgraph`.
- Persist `engine_backend` on run record.

**Step 4: Run tests**
- `uv run pytest -q tests/test_engine.py`

**Step 5: Commit**
- Commit adapter wiring.

### Task 3: Add Alternate Local Backend (Proof of Pluggability)

**Files:**
- Create: `src/bpg/engines/local/backend.py`
- Create: `src/bpg/engines/local/__init__.py`
- Modify: `src/bpg/runtime/backends.py`
- Test: `tests/test_engine_backends.py`

**Step 1: Write failing parity test**
- Same simple process runs with `langgraph` and `local` and reaches `completed`.

**Step 2: Implement local backend**
- Start with a non-distributed backend that delegates to same runtime semantics path.
- Keep public contract identical to `langgraph` backend for now.

**Step 3: Run tests**
- `uv run pytest -q tests/test_engine_backends.py tests/test_engine.py`

**Step 4: Commit**
- Commit second backend and parity coverage.

### Task 4: CLI Backend Selection

**Files:**
- Modify: `src/bpg/cli.py`
- Test: `tests/test_cli_runtime_orchestration.py`

**Step 1: Write failing CLI test**
- `bpg run ... --engine local` should pass backend into `Engine`.

**Step 2: Add `--engine` option**
- Choices: `langgraph`, `local`.

**Step 3: Run tests**
- `uv run pytest -q tests/test_cli_runtime_orchestration.py`

**Step 4: Commit**
- Commit CLI plumbing.

### Task 5: Docs and Migration Notes

**Files:**
- Modify: `README.md`
- Modify: `manual/USER_MANUAL.md`
- Modify: `docs/bpg-spec.md`

**Step 1: Document backend boundary and ownership rules**
- Clarify BPG owns semantics/state/audit.

**Step 2: Document CLI backend selection**
- Add examples for `--engine langgraph|local`.

**Step 3: Run docs-linked validation tests**
- `uv run pytest -q tests/system/test_spec_examples.py tests/system/test_manual_node_examples.py`

**Step 4: Commit**
- Commit docs updates.

---

## First-PR Scope (implemented now)

1. Add backend registry/contracts.
2. Add LangGraph backend adapter and wire `Engine` selection.
3. Add `local` backend alias for pluggability proof.
4. Add targeted unit tests for backend selection.
