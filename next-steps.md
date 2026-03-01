# Near-Term Priorities

## 1) Runtime Parallelism (High)
- Replace strictly linear LangGraph execution with branch-parallel scheduling for independent nodes.
- Preserve deterministic merge behavior for multi-input joins.
- Add stress/system tests for fanout/fanin with retries, timeouts, and cancellation.

## 2) SoD DSL (High)
- Introduce a first-class policy schema for common SoD patterns (role exclusivity, actor separation, approver constraints).
- Compile DSL rules into existing runtime checks for backward compatibility.
- Extend `bpg status` output with rule IDs and violated principals.

## 3) Policy & Audit Observability (Medium)
- Include policy violation metadata (`policy_code`, `rule_id`, principal context) in persisted node records.
- Add configurable audit tag conventions/validation (e.g., required tags per environment).
- Add CLI filtering for audit-tagged runs.

## 4) Spec/Docs Alignment Hardening (Medium)
- Reconcile spec wording with current implementation (`await_` naming, module declaration format).
- Add explicit docs for `bpg cleanup` and poll-based timeout behavior.
- Add regression tests tied to spec examples for policy/audit/cleanup semantics.

## 5) Operational Hardening (Medium)
- Add optional max-runtime safeguards per run to prevent unbounded executions.
- Add periodic maintenance command(s) for exports and interaction-state cleanup.
- Add CI gate to run dry-run suite and full coverage suite on each PR.
