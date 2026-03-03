# Pattern: Approval Workflow

```yaml
doc_metadata:
  topic: pattern_approval_workflow
  version: 1
  summary: Route uncertain or sensitive actions through explicit human approval nodes.
```

## Summary
Approval workflows insert a human gate before irreversible side effects.

## When to use
Use for spending approvals, policy exceptions, or high-risk customer actions.

## Core idea
Separate assessment from authorization and keep the edge condition explicit.

## Example
```text
task -> confidence_check -> human_review -> continue
```

## Common mistakes
- Triggering side effects before approval branch resolves.
- Omitting timeout/escalation behavior for human nodes.

## Related pages
- [Human Steps Concept](../concepts/human_steps.md)
- [Add Human Review Guide](../guides/add_human_review.md)
- [Pattern: Retry](retry_pattern.md)
