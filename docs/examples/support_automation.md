# Example: Support Automation

```yaml
doc_metadata:
  topic: example_support_automation
  version: 1
  summary: Ticket classification, response drafting, and escalation process graph.
```

## Summary
Classifies tickets, drafts responses, and escalates sensitive or low-confidence cases.

## When to use
Use for service desk workflows where automation must remain controllable.

## Core idea
Use confidence- and policy-based branching to maintain quality and safety.

## Example
```text
ingest_ticket -> classify -> draft_response -> policy_check -> send_or_escalate
```

## Common mistakes
- Sending responses without policy checks.
- Omitting explicit mapping of customer context fields.

## Related pages
- [Guide: Add AI Step](../guides/add_ai_step.md)
- [Guide: Add Human Review](../guides/add_human_review.md)
- [AI Prompt Patterns](../ai/prompt_patterns.md)
