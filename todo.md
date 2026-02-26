# BPG Spec Gap TODO (vs `docs/bpg-spec.md`)

## High Priority

- [x] Create test suite for all major functionality
  - Use dry-run semantics
  - This means dry-runs must have useful output
- [x] Enforce trigger constraints from §4.4 in compile-time validation.
  - Missing: trigger must have no incoming edges.
  - Current behavior: validator only checks that trigger exists; incoming edges are allowed.
  - Impact: runtime can treat a different node as the effective entrypoint (it treats "no incoming edges" as trigger behavior), causing incorrect execution semantics.
  - Relevant files: `src/bpg/compiler/validator.py`, `src/bpg/runtime/langgraph_runtime.py`.

- [x] Enforce human-node timeout contract from §9.
  - Missing: all human nodes (`slack.interactive`, `dashboard.form`) must require both `config.timeout` and `on_timeout.out`.
  - Current behavior: timeout fallback is supported, but not required by validation.
  - Impact: human nodes can time out without deterministic continuation behavior mandated by spec.
  - Relevant files: `src/bpg/compiler/validator.py`.

- [x] Implement full edge `on_failure` action semantics from §4.2 and §10.
  - Missing/incorrect: runtime currently handles `route` only; `notify` and explicit `fail` behavior are not implemented.
  - Current behavior: `on_failure.notify` is parsed but ignored at runtime.
  - Relevant files: `src/bpg/runtime/langgraph_runtime.py`, `src/bpg/models/schema.py`.

- [x] Persist immutable append-only run history as required by §2 and §7.
  - Missing/incorrect: per-node records are overwritten by filename (`nodes/<node>.yaml`), and there is no immutable append-only event log persisted as such.
  - Impact: weak auditability vs spec guarantees.
  - Relevant files: `src/bpg/state/store.py`, `src/bpg/runtime/engine.py`.

## Medium Priority

- [x] Enforce required process sections from §4 (`types`, `nodes`, `edges`, `trigger`).
  - Missing/incorrect: model allows empty `types` by default and no explicit validation enforces presence of at least one type definition (inline or imported).
  - Relevant files: `src/bpg/models/schema.py`, `src/bpg/compiler/validator.py`.

- [x] Align provider contract method naming with §3.3.
  - Missing/incorrect: spec names the blocking call `await(...)`; implementation uses `await_result(...)`.
  - Impact: API contract drift between spec and code.
  - Relevant files: `src/bpg/providers/base.py`, all provider implementations.

- [x] Improve multi-incoming-edge execution semantics clarity/implementation for §7 step model.
  - Current behavior: runtime selects the first satisfied incoming edge for mapping.
  - Risk: ambiguous behavior when multiple incoming edges are satisfied; spec text implies evaluating all incoming conditions before mapping.
  - Relevant files: `src/bpg/runtime/langgraph_runtime.py`.

## Lower Priority / Spec-Model Alignment

- [x] Expand apply-state metadata to explicitly store version pins/checksums as first-class fields per §6 and §11.
  - Current behavior: much of this is indirectly present in persisted process definition and deployment artifact checksums; explicit pin/checksum records are not separately modeled.
  - Relevant files: `src/bpg/state/store.py`, `src/bpg/cli.py`.

- [x] Ensure run/version association is explicit for concurrent deploy/run semantics in §6.
  - Current behavior: engine runs synchronously against the loaded process object; no explicit persisted process-version pointer on each run record.
  - Relevant files: `src/bpg/runtime/engine.py`, `src/bpg/state/store.py`.
