# Testing Processes Guide

```yaml
doc_metadata:
  topic: testing_processes
  version: 1
  summary: Validate routing and contract behavior with BPG spec-level tests.
```

## Summary
`bpg test` runs process-level behavior checks using mocks and routing assertions without external integrations.

## When to use
Use during development and CI to verify route decisions and required output contracts.

## Core idea
Test at graph semantics level to catch regressions early and deterministically.

## Example
```yaml
tests:
  - name: low_confidence_routes_to_review
    process: ./process.bpg.yaml
    input:
      request: "help"
    mocks:
      classify:
        confidence: 0.3
    expect:
      path_contains: ["classify", "review"]
```

## Common mistakes
- Depending only on provider integration tests.
- Skipping assertions on route/path behavior.

## Related pages
- [Validation Pattern](../patterns/validation_pattern.md)
- [How Agents Should Use BPG](../ai/how_agents_should_use_bpg.md)
- [Quickstart](../quickstart.md)
