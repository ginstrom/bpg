# Built-in Provider Catalog

This catalog documents provider IDs currently registered in `PROVIDER_REGISTRY`.

## 1. Core and Test Providers

| Provider ID | Purpose | Key Input Expectations | Key Config | Packaging Hints |
|---|---|---|---|---|
| `mock` | Deterministic canned outputs for tests/dev. | Any shape accepted, but output must be pre-registered for key/node/default. | Registration APIs in code (`register`, `register_for_node`, `set_default`). | none |
| `core.passthrough` | Returns input payload unchanged. | Any object payload. | none | none |
| `http.webhook` | POST payload to webhook; supports sync/async polling. | Any object payload. | `url` required; optional `async_mode`, `poll_url`, `cancel_url`, `headers`, `poll_interval`. | none (base default) |

## 2. Human Interaction Providers

| Provider ID | Purpose | Key Input Expectations | Key Config | Packaging Hints |
|---|---|---|---|---|
| `slack.interactive` | Human approval via Slack interactive buttons and resume flow. | approval fields (for example `title`, details). | `channel`, `buttons`, plus node-level `timeout` and `on_timeout.out`. | required: `SLACK_BOT_TOKEN`; optional: `SLACK_SIGNING_SECRET` |
| `dashboard.form` | Human form checkpoint in dashboard flow. | object payload merged with defaults. | optional `defaults`, plus node-level `timeout` and `on_timeout.out`. | none (base default) |

## 3. Integration / Automation Providers

| Provider ID | Purpose | Key Input Expectations | Key Config | Packaging Hints |
|---|---|---|---|---|
| `ai.anthropic` | Structured JSON output via Anthropic messages API. | object/string input normalized to prompt text. | required `model`; optional `system_prompt`, `prompt_template`, `context_fields`, `output_schema`, `temperature`, `max_tokens`, `api_key_env`, `base_url`, `dry_run`. | live: required `ANTHROPIC_API_KEY` (or `api_key_env` override) |
| `ai.openai` | Structured JSON output via OpenAI responses API. | object/string input normalized to prompt text. | required `model`; optional `system_prompt`, `prompt_template`, `context_fields`, `output_schema`, `temperature`, `max_tokens`, `api_key_env`, `base_url`, `dry_run`. | live: required `OPENAI_API_KEY` (or `api_key_env` override) |
| `ai.google` | Structured JSON output via Google Gemini generateContent API. | object/string input normalized to prompt text. | required `model`; optional `system_prompt`, `prompt_template`, `context_fields`, `output_schema`, `temperature`, `max_tokens`, `api_key_env`, `base_url`, `dry_run`. | live: required `GOOGLE_API_KEY` (or `api_key_env` override) |
| `ai.ollama` | Structured JSON output via local Ollama generate API. | object/string input normalized to prompt text. | required `model`; optional `system_prompt`, `prompt_template`, `context_fields`, `output_schema`, `temperature`, `max_tokens`, `base_url`, `dry_run`. | no required env by default |
| `ai.llm` | Compatibility alias for Anthropic-backed AI provider. | same as `ai.anthropic`. | same as `ai.anthropic`. | same as `ai.anthropic` |
| `agent.pipeline` | Baseline AI-style triage output generation. | often `title`, `severity`, optional `labels`. | optional `mock_output` override object. | none |
| `http.gitlab` | Deterministic GitLab issue metadata output for local workflows. | optional `labels`. | optional `ticket_prefix`, `ticket_id`, `issue_url`. | required: `GITLAB_TOKEN`; optional: `GITLAB_BASE_URL` |
| `queue.kafka` | Simulated publish metadata for Kafka-like flows. | `topic` in input or config. | optional `topic`, `partition`, `offset`. | none |
| `timer.delay` | Wait/sleep node for controlled pauses. | optional `duration`. | `duration` numeric seconds (or via input). | none |
| `bpg.process_call` | Triggers another deployed BPG process. | child process input payload. | required `process_name`; optional `state_dir`. | none |
| `tool.web_search` | Web search tool with dry-run/live modes. | required `query`; optional `top_k`. | optional `top_k`, `endpoint`, `api_key_env`, `require_api_key`, `timeout_seconds`, `dry_run`. | dry-run: no required env. live: requires endpoint + API key env (default `WEB_SEARCH_API_KEY`) unless disabled |
| `notify.email` | Email notification with dry-run/live SMTP modes. | required `to`, `subject`, `body`. | optional `from`, `smtp_host`, `smtp_port`, `smtp_username`, `smtp_password`, `smtp_starttls`, `dry_run`. | requires `SMTP_FROM` if no config.from; live mode also requires `SMTP_HOST` |

## 4. Data and Control-Flow Helpers

| Provider ID | Purpose | Key Input Expectations | Key Config | Packaging Hints |
|---|---|---|---|---|
| `text.parse_numbers` | Extract numbers from text. | required `text` string. | none | none |
| `math.sum_numbers` | Sum numeric list. | required `numbers` list of numeric values. | none | none |
| `fs.markdown_list` | Enumerate markdown files and emit document payloads. | input/config `root_dir`, optional `glob`. | optional `root_dir`, `glob` (default `**/*.md`). | optional: `BPG_MARKDOWN_ROOT` |
| `text.markdown_chunk` | Split markdown docs into overlapping chunks. | required `documents` list. | optional `chunk_size` and `overlap`. | none |
| `embed.text` | Deterministic baseline embeddings for chunks/queries. | either `chunks` list or `query` string. | optional embedding model selector. | none |
| `weaviate.upsert` | Baseline local index writer for search chunks/vectors. | required `items` list. | optional `store`, `store_dir`, `store_path`. | optional: `BPG_SEARCH_STORE_DIR`, `WEAVIATE_URL`, `WEAVIATE_API_KEY` |
| `weaviate.hybrid_search` | Baseline hybrid lexical+vector retrieval. | required `query`, `vector`; optional `top_k`. | optional `store`, `store_dir`, `store_path`, `alpha`, `top_k`. | optional: `BPG_SEARCH_STORE_DIR`, `WEAVIATE_URL`, `WEAVIATE_API_KEY` |
| `flow.loop` | Bounded iteration planning helper. | required `items` list. | optional `max_iterations` (int). | none |
| `flow.fanout` | Convert `items` list to branch envelopes. | required `items` list. | none | none |
| `flow.await_all` | Aggregate fanout results. | required `results` list. | none | none |

## 5. Dry-Run Mode Conventions

Providers with explicit dry-run logic:

- `tool.web_search`
- `notify.email`

Dry-run toggles:

- node config: `dry_run: true`
- env var: `BPG_DRY_RUN=1`
- env var: `BPG_EXECUTION_MODE=dry-run`

## 6. Built-in Provider IDs (quick list)

`mock`, `http.webhook`, `core.passthrough`, `ai.anthropic`, `ai.openai`, `ai.google`, `ai.ollama`, `ai.llm`, `agent.pipeline`, `dashboard.form`, `slack.interactive`, `http.gitlab`, `queue.kafka`, `timer.delay`, `flow.loop`, `flow.fanout`, `flow.await_all`, `bpg.process_call`, `text.parse_numbers`, `math.sum_numbers`, `fs.markdown_list`, `text.markdown_chunk`, `embed.text`, `weaviate.upsert`, `weaviate.hybrid_search`, `tool.web_search`, `notify.email`
