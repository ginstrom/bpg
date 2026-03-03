# Pattern: AI Evaluation Pipeline

```yaml
doc_metadata:
  topic: pattern_ai_evaluation_pipeline
  version: 1
  summary: Compose classify/extract/evaluate/review stages with confidence-based routing.
```

## Summary
This pattern chains AI tasks with explicit evaluation and optional human escalation.

## When to use
Use for document handling, ticket triage, and moderation workflows.

## Core idea
Keep each AI stage typed and add route conditions on confidence or rule checks.

## Example
```text
classify -> extract -> evaluate -> (if low confidence) human_review -> store
```

## Common mistakes
- Combining evaluation and extraction in one opaque step.
- Skipping schema validation for AI outputs.

## Related pages
- [Add AI Step Guide](../guides/add_ai_step.md)
- [Add Human Review Guide](../guides/add_human_review.md)
- [Pattern: Approval Workflow](approval_workflow.md)
