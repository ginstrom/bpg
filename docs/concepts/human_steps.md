# Human Steps Concept

```yaml
doc_metadata:
  topic: human_steps
  version: 1
  summary: Human tasks are first-class nodes with explicit timeout and escalation behavior.
```

## Summary
Human-in-the-loop nodes model review and approval work as typed steps with defined timeout semantics.

## When to use
Use human steps where model confidence is low, compliance gates are required, or external approval is mandatory.

## Core idea
Human review is declarative. Define the node contract and route to it through conditions.

## Example
```yaml
nodes:
  review:
    type: review_node@v1
    config:
      timeout: 24h

edges:
  - from: classify
    to: review
    when: classify.out.confidence < 0.8
```

## Common mistakes
- Adding ad-hoc human checks outside the graph.
- Missing timeout fallback handling for human nodes.

## Related pages
- [Add Human Review Guide](../guides/add_human_review.md)
- [Approval Workflow Pattern](../patterns/approval_workflow.md)
- [Error Codes](../reference/error_codes.md)
