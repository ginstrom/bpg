# Example: Insurance Claims

```yaml
doc_metadata:
  topic: example_insurance_claims
  version: 1
  summary: Claims intake, policy checks, fraud scoring, and adjuster review workflow.
```

## Summary
Automates claim triage while preserving human oversight for high-risk cases.

## When to use
Use as a template for regulated workflows that need explainability and escalation.

## Core idea
Automate low-risk flow; route ambiguous or risky cases to human specialists.

## Example
```text
intake -> policy_validate -> fraud_score -> adjuster_review? -> payout_or_reject
```

## Common mistakes
- Missing audit events for approval/rejection decisions.
- Hardcoding business thresholds inside provider code.

## Related pages
- [Pattern: Approval Workflow](../patterns/approval_workflow.md)
- [Pattern: Retry](../patterns/retry_pattern.md)
- [Concept: Execution](../concepts/execution.md)
