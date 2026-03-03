# Example: Compliance Review

```yaml
doc_metadata:
  topic: example_compliance_review
  version: 1
  summary: Multi-step compliance checking with deterministic evidence and approval routing.
```

## Summary
Runs automated checks and human approvals before regulated actions are finalized.

## When to use
Use for KYC/AML, policy attestations, and audit-heavy decision workflows.

## Core idea
Make every decision path explicit and replayable from canonical events.

## Example
```text
collect_data -> automated_checks -> legal_review -> compliance_approval -> finalize
```

## Common mistakes
- Storing compliance evidence outside run/event records.
- Weak type contracts for decision artifacts.

## Related pages
- [Concept: Versioning](../concepts/versioning.md)
- [Reference: Error Codes](../reference/error_codes.md)
- [AI Repair Strategies](../ai/repair_strategies.md)
