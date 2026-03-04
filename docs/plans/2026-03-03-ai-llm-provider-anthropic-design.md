# AI LLM Provider (Anthropic First) Design

## Goal
Add a reusable `ai.llm` provider that centralizes AI-node concerns (input normalization, prompt/context assembly, output schema enforcement, and typed errors), with Anthropic as the first concrete backend.

## Scope
- Implement one provider ID: `ai.llm`
- Support `vendor: anthropic` in provider config
- Enforce structured output via `config.output_schema`
- Expose packaging env requirements (`ANTHROPIC_API_KEY` by default)
- Add provider metadata and tests

## Non-goals (this phase)
- Multiple vendors in one release (`openai`, `google`, etc.)
- Streaming responses
- Advanced prompt templating DSL
- Complex JSON Schema features (we will support a pragmatic subset)

## Provider Contract
`ai.llm` configuration:
- `vendor`: currently `"anthropic"` only
- `model`: required string
- `system_prompt`: optional string
- `prompt_template`: optional string, can reference `{{input}}`
- `context_fields`: optional list of input keys to include
- `output_schema`: optional JSON-schema-like object (subset)
- `temperature`: optional number (default `0`)
- `max_tokens`: optional int (default `1024`)
- `api_key_env`: optional string (default `ANTHROPIC_API_KEY`)
- `base_url`: optional string (default Anthropic messages endpoint)
- `anthropic_version`: optional string (default `2023-06-01`)
- `dry_run`: optional bool for deterministic local behavior

Input handling:
- If input is a string, use it directly.
- If input is an object, build prompt context from selected fields or full JSON.

Output handling:
- Read model text output.
- Extract JSON (plain JSON or fenced code block).
- Parse object and validate against `output_schema` subset:
  - `type`, `required`, `properties`, `items`
- Raise typed `ProviderError` on invalid output.

## Error Model
- `invalid_config`: missing/invalid provider config
- `missing_api_key`: API key env var absent
- `unsupported_vendor`: vendor not implemented
- `llm_http_error`: HTTP-level Anthropic failure (retryable for 429/5xx)
- `llm_invalid_response`: malformed Anthropic payload
- `llm_output_not_json`: model did not return parseable JSON
- `llm_output_schema`: output failed schema checks

## Integration Points
- Register `AiLlmProvider` in `src/bpg/providers/__init__.py`
- Include in provider metadata CLI automatically via registry
- Packaging inference will pick up env requirements through `packaging_requirements`

## Testing
- Unit tests for:
  - dry-run deterministic path
  - Anthropic request shape and headers
  - API key and vendor validation
  - JSON extraction and schema enforcement failures
  - packaging requirements required/optional env behavior
  - registry includes `ai.llm`
