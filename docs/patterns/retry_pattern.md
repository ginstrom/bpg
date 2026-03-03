# Pattern: Retry

```yaml
doc_metadata:
  topic: pattern_retry
  version: 1
  summary: Model transient failures with deterministic retry behavior and event visibility.
```

## Summary
Retry patterns handle temporary provider failures while preserving deterministic state transitions.

## When to use
Use for external APIs and asynchronous systems with occasional transient errors.

## Core idea
Retries are runtime semantics, not ad-hoc provider loops hidden from process state.

## Example
```text
node_started -> node_failed -> node_retry_scheduled -> node_started -> node_completed
```

## Common mistakes
- Non-idempotent side effects without retry safety.
- Missing monitoring for repeated retry exhaustion.

## Related pages
- [Execution Concept](../concepts/execution.md)
- [CLI: bpg run](../cli/run.md)
- [Pattern: Validation](validation_pattern.md)
