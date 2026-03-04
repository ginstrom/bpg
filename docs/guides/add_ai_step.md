# Add AI Step Guide

```yaml
doc_metadata:
  topic: add_ai_step
  version: 1
  summary: Add an AI node with typed outputs and conditional routing.
```

## Summary
Insert an AI step as a node type + node instance, then wire explicit edge mappings.

## When to use
Use when adding classification, extraction, scoring, or evaluation tasks.

## Core idea
AI steps are regular nodes. Reliability comes from strict output schemas and downstream validation.

Use provider-specific AI node IDs:
- `ai.anthropic`
- `ai.openai`
- `ai.google`
- `ai.ollama`

`ai.llm` remains available as a compatibility alias to `ai.anthropic`.

## Example
```yaml
types:
  ReviewSelectIn:
    row_ids: list<number>
  ReviewBatchIn:
    rows: list<object>
  ReviewBatchOut:
    items: list<object>

node_types:
  select_reviews@v1:
    in: ReviewSelectIn
    out: ReviewBatchIn
    provider: core.dataset.select_rows
    version: v1
    config_schema:
      rows: list<object>

  classify@v1:
    in: ReviewBatchIn
    out: ReviewBatchOut
    provider: ai.google
    version: v1
    config_schema:
      model: string
      system_prompt: string
      temperature: number?
      max_tokens: integer?
      api_key_env: string?

nodes:
  select:
    type: select_reviews@v1
    config:
      rows: ${IMDB_ROWS}

  classify:
    type: classify@v1
    config:
      model: gemini-2.5-flash-lite
      api_key_env: GOOGLE_API_KEY
      system_prompt: |
        Return strict JSON: {"items":[...]}

edges:
  - from: ingest
    to: select
    with:
      row_ids: ingest.out.row_ids
  - from: select
    to: classify
    with:
      rows: select.out.rows

artifacts:
  - name: classified_items
    from: classify.out.items
    format: jsonl
```

## Common mistakes
- Leaving AI outputs untyped or too loose for downstream use.
- Coupling retries/branching inside provider logic.
- Using ambiguous trigger inputs for row selection (use typed `row_ids: list<number>`).
- Forgetting to declare artifacts when downstream systems need stable files.

## Related pages
- [Nodes Concept](../concepts/nodes.md)
- [Provider Interface Reference](../reference/provider_interface.md)
- [AI Evaluation Pipeline Pattern](../patterns/ai_evaluation_pipeline.md)
