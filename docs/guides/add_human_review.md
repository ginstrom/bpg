# Add Human Review Guide

```yaml
doc_metadata:
  topic: add_human_review
  version: 1
  summary: Add a human review node for low-confidence or policy-gated decisions.
```

## Summary
Introduce a human node and route to it conditionally based on upstream signals.

## When to use
Use when confidence thresholds, approvals, or compliance checks are required.

## Core idea
Human review is modeled as a typed node with explicit timeout policy.

## Example
```yaml
edges:
  - from: classify
    to: review
    when: classify.out.confidence < 0.8
    with:
      summary: classify.out.summary
```

## Common mistakes
- Not declaring clear inputs for the reviewer.
- Missing timeout fallback behavior.

## Related pages
- [Human Steps Concept](../concepts/human_steps.md)
- [Approval Workflow Pattern](../patterns/approval_workflow.md)
- [Debug Validation Errors Guide](debug_validation_errors.md)
