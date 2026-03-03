# Example: Document Pipeline

```yaml
doc_metadata:
  topic: example_document_pipeline
  version: 1
  summary: End-to-end document processing flow with confidence-based review.
```

## Summary
Processes inbound text documents, extracts fields, routes uncertain results to review, and stores outcomes.

## When to use
Use as a baseline architecture for AI-assisted document operations.

## Core idea
Typed stages + explicit conditions create reliable and inspectable automation.

## Example
```text
upload -> classify -> extract -> confidence_check -> review? -> store
```

## Common mistakes
- Directly storing extraction output without confidence gating.
- Missing typed contract between extraction and storage.

## Related pages
- [Pattern: AI Evaluation Pipeline](../patterns/ai_evaluation_pipeline.md)
- [Guide: Build Process](../guides/build_process.md)
- [Concept: Human Steps](../concepts/human_steps.md)
