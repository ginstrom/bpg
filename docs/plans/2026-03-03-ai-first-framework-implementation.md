# AI-First Framework Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Position BPG as an AI-first application development framework where agents can author, validate, patch, test, and evolve process specs safely with machine-readable feedback and minimal diff churn.

**Architecture:** Build an agent contract around a canonical IR, structured compiler diagnostics, patch-based edits, provider introspection, and deterministic runtime semantics/events. Keep BPG as semantic owner; execution engines remain adapters behind the orchestrator boundary already introduced in Phase 1/2.

**Tech Stack:** Python 3.12, Pydantic, Typer CLI, existing compiler/runtime/orchestrator/event store, pytest, uv.

---

## Baseline (already complete)

1. Pluggable execution backend boundary is in place (`langgraph`, `local`).
2. Engine-neutral orchestrator loop exists for local backend.
3. Full suite is currently passing on `main`.

This plan starts from that baseline and focuses on AI-first authoring, diagnostics, and agent tooling.

---

## Milestone Timeline (execution-focused)

| Milestone | Target (P50) | Error Bar / Range | Confidence | Depends On | Owner Role |
| --- | --- | --- | --- | --- | --- |
| M1 Structured diagnostics + `doctor` | 4 days | 3-6 days | High | Baseline compiler/CLI | Compiler + CLI engineer |
| M2 Provider introspection + metadata contract | 3 days | 2-5 days | High | M1 error model types | Provider platform engineer |
| M3 Canonical IR + `fmt` | 5 days | 4-8 days | Medium | M1 diagnostics | Compiler engineer |
| M4 Patch workflow (`apply-patch`, `suggest-fix`) | 6 days | 5-9 days | Medium | M1 + M3 | Compiler/CLI engineer |
| M5 `plan --explain --json` compatibility + blast radius | 4 days | 3-7 days | Medium | M3 event/schema diffs | Runtime + planner engineer |
| M6 Spec test harness (`bpg test`) | 7 days | 5-10 days | Medium | M3 + M4 | Runtime/test engineer |
| M7 Event schema v1 + replay + determinism hardening | 6 days | 5-10 days | Medium | M5 + M6 | Runtime engineer |
| M8 AI-init scaffolding + CI AI-friendliness metrics | 5 days | 4-8 days | Medium | M1-M7 | DX + QA engineer |

---

### Task 1: Structured Compiler Error Model (Foundation)

**Files:**
- Create: `src/bpg/compiler/errors.py`
- Modify: `src/bpg/compiler/parser.py`
- Modify: `src/bpg/compiler/validator.py`
- Modify: `src/bpg/compiler/expr.py` (or keep in `runtime/expr.py` and add compiler-facing wrappers)
- Modify: `src/bpg/cli.py`
- Test: `tests/test_compiler.py`
- Test: `tests/test_cli_plan.py`

**Steps:**
1. Introduce canonical diagnostic model with fields:
   - `error_code`, `path`, `message`, `fix`, `example_patch`, `schema_excerpt`, `severity`.
2. Replace free-form `ValidationError`/`ParseError` string output paths with structured diagnostics payload.
3. Add error-code registry constants (`E_*`) and freeze code names in docs.
4. Add CLI printer for human + `--json` output mode.

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_compiler.py tests/test_cli_plan.py`

**Commit:**
- `git commit -m "Add structured compiler diagnostics with stable error codes"`

---

### Task 2: `bpg doctor` (Agent-oriented diagnostics)

**Files:**
- Modify: `src/bpg/cli.py`
- Modify: `src/bpg/compiler/parser.py`
- Modify: `src/bpg/compiler/validator.py`
- Create: `tests/test_cli_doctor.py`
- Modify: `README.md`
- Modify: `manual/USER_MANUAL.md`

**Steps:**
1. Add `bpg doctor <process_file> [--json]` command.
2. Execute parse + validate + compile checks and return grouped diagnostics.
3. Include fix hints and patch suggestions for common classes:
   - missing required input mappings
   - unknown provider
   - unknown type ref
   - invalid `when` expression
4. Make non-zero exit on diagnostics with `severity=error`.

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_cli_doctor.py tests/test_compiler.py`

**Commit:**
- `git commit -m "Add bpg doctor with machine-readable repair diagnostics"`

---

### Task 3: Provider Metadata Contract + Introspection CLI

**Files:**
- Create: `src/bpg/providers/metadata.py`
- Modify: `src/bpg/providers/base.py`
- Modify: `src/bpg/providers/__init__.py`
- Modify: `src/bpg/providers/builtin.py`
- Modify: `src/bpg/cli.py`
- Create: `tests/test_cli_provider_describe.py`
- Modify: `tests/test_providers.py`

**Steps:**
1. Define `ProviderMetadata` model with:
   - name, description, input_schema, output_schema
   - side_effects enum, idempotency enum, latency_class enum
   - examples (2-3 blocks)
2. Require each provider class to expose metadata (class var or method).
3. Add `bpg providers list [--json]` and `bpg providers describe <id> [--json]`.
4. Validate provider registry completeness in tests (all providers have metadata).

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_providers.py tests/test_cli_provider_describe.py`

**Commit:**
- `git commit -m "Add provider metadata model and provider introspection CLI"`

---

### Task 4: Canonical ProcessSpec IR + Normalization

**Files:**
- Modify: `src/bpg/compiler/ir.py`
- Create: `src/bpg/compiler/normalize.py`
- Modify: `src/bpg/models/schema.py`
- Modify: `src/bpg/compiler/parser.py`
- Test: `tests/test_compiler.py`
- Create: `tests/test_normalize.py`

**Steps:**
1. Introduce explicit canonical IR dataclasses:
   - `ProcessSpecIR`, `NodeSpecIR`, `EdgeSpecIR`, `TypeRefIR`.
2. Add normalization pass enforcing deterministic ordering:
   - nodes by id, edges by id, mapping keys sorted, stable quoting policy inputs.
3. Ensure parse -> normalize -> IR is deterministic for equivalent YAML orderings.
4. Add invariance tests using multiple equivalent YAML fixtures.

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_normalize.py tests/test_compiler.py`

**Commit:**
- `git commit -m "Add canonical ProcessSpec IR and deterministic normalization pass"`

---

### Task 5: Canonical Formatter (`bpg fmt`)

**Files:**
- Create: `src/bpg/compiler/formatter.py`
- Modify: `src/bpg/cli.py`
- Create: `tests/test_cli_fmt.py`
- Modify: `README.md`
- Modify: `manual/USER_MANUAL.md`

**Steps:**
1. Add `bpg fmt <process_file> [--check] [--write]` command.
2. Format by serializing normalized IR; do not mutate semantics.
3. `--check` returns non-zero if file is not canonical.
4. Ensure formatter preserves comments only if currently supported; if not, document limitation and snapshot expected behavior.

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_cli_fmt.py tests/test_normalize.py`

**Commit:**
- `git commit -m "Add canonical bpg fmt for deterministic YAML output"`

---

### Task 6: Patch Workflow (`apply-patch` + fix suggestions)

**Files:**
- Create: `src/bpg/compiler/patching.py`
- Modify: `src/bpg/cli.py`
- Modify: `src/bpg/compiler/errors.py`
- Create: `tests/test_cli_apply_patch.py`
- Create: `tests/test_patching.py`

**Steps:**
1. Add JSON Patch support on canonical IR with validation.
2. Add `bpg apply-patch <process_file> <patch_file> [--in-place]`.
3. Add `bpg suggest-fix <process_file> [--json]`:
   - emits patches sourced from diagnostics produced by `doctor`.
4. Guarantee patch output is re-formatted through `bpg fmt` for stable diffs.

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_patching.py tests/test_cli_apply_patch.py tests/test_cli_doctor.py`

**Commit:**
- `git commit -m "Add IR JSON patch workflow and suggest-fix command"`

---

### Task 7: Deterministic `when` DSL Grammar + Linting Precision

**Files:**
- Modify: `src/bpg/runtime/expr.py`
- Create: `src/bpg/compiler/expr_lint.py`
- Modify: `src/bpg/compiler/validator.py`
- Create: `tests/test_expr_lint.py`

**Steps:**
1. Freeze restricted grammar (comparisons, boolean ops, existence checks only).
2. Emit token-level diagnostics for parse failures with operator/operand location.
3. Reject unsupported constructs explicitly (functions, loops, arbitrary calls).
4. Add linter-style error codes (`E_EXPR_*`) to diagnostics contract.

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_expr_lint.py tests/test_compiler.py`

**Commit:**
- `git commit -m "Harden when-expression grammar with token-level diagnostics"`

---

### Task 8: Plan Explainability (`bpg plan --explain --json`)

**Files:**
- Modify: `src/bpg/compiler/planner.py`
- Modify: `src/bpg/cli.py`
- Create: `tests/test_cli_plan_explain.py`
- Modify: `tests/test_planner.py`

**Steps:**
1. Extend plan artifacts with:
   - graph summary
   - node/edge/schema diffs
   - compatibility warnings
   - blast radius estimate (affected active versions/runs where possible)
2. Add `--explain` and structured JSON schema for output.
3. Ensure backward compatibility for existing `bpg plan` text output.

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_planner.py tests/test_cli_plan_explain.py`

**Commit:**
- `git commit -m "Add explainable machine-readable planning output"`

---

### Task 9: Spec-level Test Runner (`bpg test`)

**Files:**
- Create: `src/bpg/testing/models.py`
- Create: `src/bpg/testing/runner.py`
- Modify: `src/bpg/cli.py`
- Create: `tests/test_cli_spec_test.py`
- Create: `tests/system/test_spec_test_runner.py`

**Steps:**
1. Define spec test schema in YAML (input, mocks, expectations).
2. Implement runner using local backend + provider mock overrides.
3. Add assertions for:
   - route/path contains
   - required output fields
   - event sequence snapshots (golden)
4. Provide `--json` output for agent consumption.

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_cli_spec_test.py tests/system/test_spec_test_runner.py`

**Commit:**
- `git commit -m "Add spec-level bpg test runner with mocks and routing assertions"`

---

### Task 10: Event Schema v1 + Replay Contract

**Files:**
- Create: `src/bpg/runtime/events.py`
- Modify: `src/bpg/runtime/orchestrator.py`
- Modify: `src/bpg/state/store.py`
- Modify: `src/bpg/cli.py`
- Create: `tests/test_events.py`
- Create: `tests/test_cli_replay.py`

**Steps:**
1. Introduce explicit event schema versions and event model validators.
2. Ensure append-only event log can fully reconstruct run/node derived state.
3. Add `bpg replay <run_id>` command to rebuild status from events.
4. Add deterministic scheduling checks (same input/spec => same route decisions).

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_events.py tests/test_cli_replay.py tests/test_engine_backends.py`

**Commit:**
- `git commit -m "Standardize event schema v1 and add replay command"`

---

### Task 11: Intent-to-Scaffold (`bpg init --from-intent`)

**Files:**
- Modify: `src/bpg/cli.py`
- Create: `src/bpg/scaffold/intent.py`
- Create: `src/bpg/scaffold/templates.py`
- Create: `tests/test_cli_init_intent.py`

**Steps:**
1. Add `bpg init --from-intent "..."` with deterministic non-LLM heuristic scaffold v1.
2. Generate canonical YAML skeleton with explicit node/edge IDs.
3. Emit machine-readable TODO manifest (`T_PROVIDER_SELECT`, `T_MAPPING`, etc.).
4. Pipe output through normalization/formatter before write.

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/test_cli_init_intent.py tests/test_cli_fmt.py`

**Commit:**
- `git commit -m "Add intent-based process scaffold generation with structured TODOs"`

---

### Task 12: AI-Friendliness CI Metrics + Benchmark Corpus

**Files:**
- Create: `tests/ai_friendly/corpus/*.yaml`
- Create: `tests/ai_friendly/test_repair_rounds.py`
- Create: `tests/ai_friendly/test_diff_minimality.py`
- Create: `tests/ai_friendly/test_provider_selection.py`
- Modify: `.github/workflows/ci.yml` (or existing CI config)
- Modify: `README.md`

**Steps:**
1. Add benchmark corpus for representative process intents and failure classes.
2. Measure and publish in CI:
   - validity after 0/1/2 repair rounds
   - median diff lines per insert-step edit
   - example-patch repair success rate
   - provider selection accuracy
3. Fail CI on regression thresholds once baseline stabilizes.

**Verification:**
- `source .venv/bin/activate && uv run pytest -q tests/ai_friendly`

**Commit:**
- `git commit -m "Add AI-friendliness benchmark suite and CI metrics gates"`

---

## Scope Boundaries (keep AI-first)

1. No general-purpose scripting in DSL.
2. No implicit data passing across edges.
3. No undocumented runtime semantics outside machine-readable schemas.
4. No provider without metadata and typed I/O contracts.
5. No non-deterministic formatter output.

---

## Definition of Done for “AI-First Positioning”

1. Agent can scaffold via `bpg init --from-intent`, run `bpg doctor`, apply `bpg suggest-fix` patch, and pass validation with no manual prose lookup.
2. `bpg fmt` + patch workflow yields minimal, reviewable diffs for localized graph edits.
3. Provider discovery is fully machine-readable (`list/describe` JSON).
4. `bpg test` validates routing and contracts without external integrations.
5. Event log + replay is engine-agnostic and reconstructs state independently.
6. CI tracks and enforces AI-friendliness metrics trends.

---

## First 30-Day Action Plan

1. Week 1: Task 1-2 (structured diagnostics + doctor).
2. Week 2: Task 3-5 (provider metadata/introspection + canonical IR/fmt).
3. Week 3: Task 6-8 (patch workflow + expression lint precision + explain plan JSON).
4. Week 4: Task 9-10 (spec test runner + event v1/replay).
5. Stretch: Task 11-12 (intent scaffold + CI metrics), gated on week-3/4 stability.

