# BPG Spec Gap TODO

Scope: Re-evaluated against `docs/bpg-spec.md` (v0.2 draft) and current codebase on 2026-02-26.

## P0 - Correctness / Spec Compliance ✅ COMPLETE (2026-02-26)

- [x] Implement real run engine and CLI runtime commands (`bpg run`, `bpg status`).
  - `Engine.trigger()` implemented; `bpg run` and `bpg status` CLI commands implemented.
  - Spec refs: §7 Process Run Lifecycle, §7 Node Execution Semantics.

- [x] Implement run persistence APIs in `StateStore`.
  - Implemented: `create_run`, `load_run`, `update_run`, `list_runs`, `save_node_record`, `load_node_record`.
  - Spec refs: §7 immutable append-only execution log, per-node execution records.

- [x] Fix timeout semantics for human nodes so `on_timeout.out` continues the run.
  - When `on_timeout.out` is set, node is marked COMPLETED in node_statuses (routing continues). Log entry records `status: timed_out, synthetic: true` for audit.
  - Spec refs: §9 Timeout Handling, §7 Node Execution Semantics.

- [x] Enforce runtime input/output type validation at execution time.
  - `_validate_payload()` in langgraph_runtime.py validates trigger input, node input before invoke, node output after await_result.
  - Spec refs: §7 step 4 and step 7.

- [x] Ensure process-level failure state is represented and surfaced.
  - `Engine.trigger()` computes `run_status=failed` when any node failed without an established failure route; persisted to StateStore.
  - Spec refs: §10 Process-Level Failure Behavior.

- [x] Fix provider registry/runtime defaults for built-in provider IDs used by spec/examples.
  - `slack.interactive` registered (store now Optional). Stub providers registered for `agent.pipeline`, `dashboard.form`, `http.gitlab`, `timer.delay`, `queue.kafka`.
  - Spec refs: §3.3 Built-in Provider Types.

## P1 - Compile/Plan/Apply Completeness

- [ ] Strengthen provider config validation from "required/extra keys" to typed schema enforcement.
  - Validate primitives, enums, lists, duration/datetime formats from `config_schema`.
  - Spec refs: §5 step 7, §3.1 primitive/type rules.

- [ ] Enforce edge mapping completeness even when `with` is omitted.
  - Today, no `with` skips type-checking and runtime passes `{}`.
  - Required fields for target input schema should still be satisfied or explicitly mapped.
  - Spec refs: §4.3 Data Mapping Rules.

- [ ] Allow non-string literal mapping values in `with`.
  - `Edge.mapping` is currently `Dict[str, str]`; spec allows strings, numbers, booleans.
  - Spec refs: §4.3 Data Mapping Rules.

- [ ] Move semantic validation responsibilities into validator phase per spec steps.
  - Edge `with` type-check and `when` validation currently happen in IR compile phase.
  - Spec refs: §5 Compilation Steps ordering.

- [ ] Make plan diff operate on execution IR + provider artifacts, not only raw process object diff.
  - Include deterministic counts and artifact/type change reporting closer to spec output.
  - Spec refs: §5 step 9, §5 Plan Output Format.

- [ ] Persist IR/version pins/checksums in state.
  - Persist process definition hash plus node type pins, type pins, provider artifact checksums/references.
  - Spec refs: §6 step 4-5, §11 Processes.

- [ ] Harden apply drift checks.
  - Current hash check covers process record hash, but not explicit provider artifact drift/IR drift checks.
  - Spec refs: §6 step 1.

## P2 - Model and Versioning Gaps

- [ ] Align `NodeType` model with spec versioning contract.
  - Spec requires `version` field; model currently has no explicit `version` field and relies on key naming only.
  - Validate semver policy and key/version consistency.
  - Spec refs: §3.2 required fields, §11 Node Types.

- [ ] Enforce type immutability/versioning at publish/apply boundaries.
  - Detect and block breaking changes to existing published types without version bump.
  - Spec refs: §3.1 Type Rules, §11 Types.

- [ ] Validate process output references.
  - Ensure `output` points to a valid node output field and define null semantics consistently if node not executed.
  - Spec refs: §4.5 Process Output.

## P3 - Missing Major Spec Areas

- [ ] Implement modules system (`module`, inputs/outputs, scoped nodes, versioning).
  - Spec refs: §12 Modules.

- [ ] Implement security/policy validation and enforcement.
  - Add structured policy schema and runtime enforcement hooks for access control, SoD, PII redaction, audit retention/export, escalation.
  - Spec refs: §13 Security & Policy.

- [ ] Add provider-state isolation and stronger execution guarantees tests.
  - Add explicit tests for guarantees in §14 (immutable history, isolation boundaries, determinism boundaries).

## Test/Quality Follow-ups

- [ ] Add end-to-end tests for CLI `run/status` and persisted run lifecycle.
- [x] Add tests for timeout fallback continuation (`on_timeout.out`) and downstream edge firing.
- [x] Add tests for strict runtime type validation failures (trigger input, mapping input, provider output).
- [x] Add tests for process-level failure state transitions.
- [ ] Add tests for policy enforcement and modules once implemented.

## Current Baseline

- Test suite currently passes: `126 passed` via `uv run pytest -q` (as of 2026-02-26, after P0 implementation).
