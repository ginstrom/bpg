# AI Provider Split (Base + Vendor Nodes) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Refactor `ai.llm` into a shared AI base provider plus vendor-specific providers (`ai.anthropic`, `ai.openai`, `ai.google`, `ai.ollama`) while keeping `ai.llm` as a compatibility alias.

**Architecture:** Move common behavior (prompt/context shaping, JSON extraction, schema validation, dry-run behavior, typed provider errors) into a reusable base class in `src/bpg/providers/ai/base.py`. Implement one provider class per vendor using thin adapters for request/response translation. Register all vendor IDs in provider registry and preserve `ai.llm` by mapping it to Anthropic behavior during migration.

**Tech Stack:** Python 3, existing Provider interface, `urllib.request`, pytest, uv, project virtualenv (`.venv`).

---

### Task 1: Restructure AI provider package with shared base

**Files:**
- Create: `src/bpg/providers/ai/__init__.py`
- Create: `src/bpg/providers/ai/base.py`
- Create: `src/bpg/providers/ai/anthropic.py`
- Create: `src/bpg/providers/ai/openai.py`
- Create: `src/bpg/providers/ai/google.py`
- Create: `src/bpg/providers/ai/ollama.py`
- Modify: `src/bpg/providers/ai.py`

**Step 1: Write the failing test**

Add import-level coverage in `tests/test_providers.py`:

```python
from bpg.providers.ai import (
    AiAnthropicProvider,
    AiGoogleProvider,
    AiOllamaProvider,
    AiOpenAIProvider,
)
```

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "AiOpenAIProvider or AiGoogleProvider or AiOllamaProvider" -q
```
Expected: FAIL with import error for missing classes/modules.

**Step 2: Run test to verify it fails**

Run the same command and confirm unresolved import failures.

**Step 3: Write minimal implementation**

Create shared base and vendor class shells:

```python
# src/bpg/providers/ai/base.py
class BaseAiProvider(Provider):
    provider_id = "ai.base"
```

```python
# src/bpg/providers/ai/anthropic.py
class AiAnthropicProvider(BaseAiProvider):
    provider_id = "ai.anthropic"
```

```python
# src/bpg/providers/ai/openai.py
class AiOpenAIProvider(BaseAiProvider):
    provider_id = "ai.openai"
```

```python
# src/bpg/providers/ai/google.py
class AiGoogleProvider(BaseAiProvider):
    provider_id = "ai.google"
```

```python
# src/bpg/providers/ai/ollama.py
class AiOllamaProvider(BaseAiProvider):
    provider_id = "ai.ollama"
```

`src/bpg/providers/ai.py` becomes compatibility re-export:

```python
from bpg.providers.ai.anthropic import AiAnthropicProvider as AiLlmProvider
```

**Step 4: Run test to verify it passes**

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "AiOpenAIProvider or AiGoogleProvider or AiOllamaProvider" -q
```
Expected: PASS for import checks.

**Step 5: Commit**

```bash
git add src/bpg/providers/ai.py src/bpg/providers/ai tests/test_providers.py
git commit -m "refactor(ai): scaffold base and vendor provider modules"
```

### Task 2: Move shared AI logic into BaseAiProvider

**Files:**
- Modify: `src/bpg/providers/ai/base.py`
- Modify: `src/bpg/providers/ai/anthropic.py`
- Modify: `tests/test_providers.py`

**Step 1: Write the failing test**

Port existing Anthropic tests to target `AiAnthropicProvider` and add one base behavior test:

```python
def test_ai_base_dry_run_applies_output_schema():
    provider = AiAnthropicProvider()
    with pytest.raises(ProviderError, match="output failed schema checks"):
        provider.invoke(
            {"text": "x"},
            {"dry_run": True, "mock_output": {"risk": 1}, "output_schema": {"type": "object", "properties": {"risk": {"type": "string"}}}},
            _ctx(node_name="extract"),
        )
```

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "ai_base_dry_run_applies_output_schema or ai_llm_rejects_output_schema_mismatch" -q
```
Expected: FAIL due to missing migrated behavior.

**Step 2: Run test to verify it fails**

Run the command and confirm failing assertions.

**Step 3: Write minimal implementation**

Move reusable logic from old `AiLlmProvider` to base:

```python
class BaseAiProvider(Provider):
    env_var_default = ""
    default_base_url = ""

    def invoke(self, input, config, context):
        if _is_truthy(config.get("dry_run")):
            output = config.get("mock_output") or {"text": _normalize_input(input)}
            _validate_schema(output, config.get("output_schema"))
            return _completed_handle(self.provider_id, context.idempotency_key, output)
        payload = self._build_vendor_payload(input, config, context)
        response = self._send_request(payload, config, context)
        output = self._parse_vendor_response(response)
        _validate_schema(output, config.get("output_schema"))
        return _completed_handle(self.provider_id, context.idempotency_key, output)
```

Anthropic class implements only vendor hooks (`_build_vendor_payload`, `_send_request`, `_parse_vendor_response`).

**Step 4: Run test to verify it passes**

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "ai_llm_anthropic_live_mode_calls_endpoint_and_parses_json or ai_base_dry_run_applies_output_schema" -q
```
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/providers/ai/base.py src/bpg/providers/ai/anthropic.py tests/test_providers.py
git commit -m "refactor(ai): centralize shared ai provider behavior in base class"
```

### Task 3: Implement OpenAI provider

**Files:**
- Modify: `src/bpg/providers/ai/openai.py`
- Modify: `tests/test_providers.py`

**Step 1: Write the failing test**

Add tests:

```python
def test_ai_openai_live_mode_calls_endpoint_and_parses_json():
    provider = AiOpenAIProvider()
    ctx = _ctx(node_name="extract")
    # patch urlopen and OPENAI_API_KEY, assert Authorization header and parsed output
```

```python
def test_ai_openai_requires_api_key():
    provider = AiOpenAIProvider()
    with patch.dict("os.environ", {}, clear=True):
        with pytest.raises(ProviderError, match="missing required env OPENAI_API_KEY"):
            provider.invoke({"text": "x"}, {"model": "gpt-4.1-mini"}, _ctx(node_name="extract"))
```

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "ai_openai" -q
```
Expected: FAIL.

**Step 2: Run test to verify it fails**

Run the command and confirm failures.

**Step 3: Write minimal implementation**

Implement endpoint/headers and response parsing:

```python
class AiOpenAIProvider(BaseAiProvider):
    provider_id = "ai.openai"
    env_var_default = "OPENAI_API_KEY"
    default_base_url = "https://api.openai.com/v1/responses"

    def _headers(self, api_key, context):
        return {
            "content-type": "application/json",
            "authorization": f"Bearer {api_key}",
            "x-idempotency-key": context.idempotency_key,
        }
```

Ensure parser extracts text from OpenAI response object and feeds `_parse_llm_json`.

**Step 4: Run test to verify it passes**

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "ai_openai" -q
```
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/providers/ai/openai.py tests/test_providers.py
git commit -m "feat(ai): add openai provider implementation"
```

### Task 4: Implement Google provider

**Files:**
- Modify: `src/bpg/providers/ai/google.py`
- Modify: `tests/test_providers.py`

**Step 1: Write the failing test**

Add tests for Google model call and API key requirement:

```python
def test_ai_google_live_mode_calls_endpoint_and_parses_json(): ...
def test_ai_google_requires_api_key(): ...
```

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "ai_google" -q
```
Expected: FAIL.

**Step 2: Run test to verify it fails**

Run the same command and confirm failures.

**Step 3: Write minimal implementation**

```python
class AiGoogleProvider(BaseAiProvider):
    provider_id = "ai.google"
    env_var_default = "GOOGLE_API_KEY"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
```

Implement payload mapping to `contents` format and parse text from candidate content parts before JSON extraction.

**Step 4: Run test to verify it passes**

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "ai_google" -q
```
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/providers/ai/google.py tests/test_providers.py
git commit -m "feat(ai): add google provider implementation"
```

### Task 5: Implement Ollama provider

**Files:**
- Modify: `src/bpg/providers/ai/ollama.py`
- Modify: `tests/test_providers.py`

**Step 1: Write the failing test**

Add tests for local endpoint behavior and no required API key:

```python
def test_ai_ollama_live_mode_calls_local_endpoint_and_parses_json(): ...
def test_ai_ollama_packaging_requirements_no_required_env(): ...
```

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "ai_ollama" -q
```
Expected: FAIL.

**Step 2: Run test to verify it fails**

Run and confirm failures.

**Step 3: Write minimal implementation**

```python
class AiOllamaProvider(BaseAiProvider):
    provider_id = "ai.ollama"
    env_var_default = ""
    default_base_url = "http://localhost:11434/api/generate"
```

Implement request with `model`, `prompt`, `stream=False`; parse `response` text and then `_parse_llm_json`.

**Step 4: Run test to verify it passes**

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "ai_ollama" -q
```
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/providers/ai/ollama.py tests/test_providers.py
git commit -m "feat(ai): add ollama provider implementation"
```

### Task 6: Register providers and keep ai.llm compatibility alias

**Files:**
- Modify: `src/bpg/providers/__init__.py`
- Modify: `tests/test_providers.py`
- Modify: `tests/test_cli_provider_describe.py`

**Step 1: Write the failing test**

Add registry tests:

```python
def test_provider_registry_includes_vendor_ai_provider_ids():
    assert "ai.anthropic" in PROVIDER_REGISTRY
    assert "ai.openai" in PROVIDER_REGISTRY
    assert "ai.google" in PROVIDER_REGISTRY
    assert "ai.ollama" in PROVIDER_REGISTRY
    assert "ai.llm" in PROVIDER_REGISTRY
```

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py -k "vendor_ai_provider_ids" -q
```
Expected: FAIL.

**Step 2: Run test to verify it fails**

Run and confirm missing keys.

**Step 3: Write minimal implementation**

Update imports and registry:

```python
from bpg.providers.ai import (
    AiAnthropicProvider,
    AiGoogleProvider,
    AiLlmProvider,
    AiOllamaProvider,
    AiOpenAIProvider,
)

PROVIDER_REGISTRY = {
    ...
    AiAnthropicProvider.provider_id: AiAnthropicProvider,
    AiOpenAIProvider.provider_id: AiOpenAIProvider,
    AiGoogleProvider.provider_id: AiGoogleProvider,
    AiOllamaProvider.provider_id: AiOllamaProvider,
    AiLlmProvider.provider_id: AiLlmProvider,  # compatibility alias
}
```

**Step 4: Run test to verify it passes**

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py tests/test_cli_provider_describe.py -k "ai or provider" -q
```
Expected: PASS for registry/metadata checks.

**Step 5: Commit**

```bash
git add src/bpg/providers/__init__.py tests/test_providers.py tests/test_cli_provider_describe.py
git commit -m "feat(ai): register vendor-specific providers and retain ai.llm alias"
```

### Task 7: Update packaging inference for all AI providers

**Files:**
- Modify: `tests/test_packaging_inference.py`

**Step 1: Write the failing test**

Add package inference coverage for env vars:

```python
def test_provider_requirements_add_env_for_ai_openai_google_ollama(tmp_path: Path):
    # process includes ai.openai, ai.google, ai.ollama
    # assert OPENAI_API_KEY and GOOGLE_API_KEY required; ollama none required
```

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_packaging_inference.py -k "ai_openai_google_ollama" -q
```
Expected: FAIL.

**Step 2: Run test to verify it fails**

Run and confirm missing requirements behavior.

**Step 3: Write minimal implementation**

If needed, adjust provider `packaging_requirements` in `BaseAiProvider` and vendor overrides:

```python
def packaging_requirements(self, config):
    if _is_truthy(config.get("dry_run")):
        return {"services": [], "required_env": [], "optional_env": [self.env_var_default] if self.env_var_default else []}
    return {"services": [], "required_env": [self.env_var_default] if self.env_var_default else [], "optional_env": []}
```

**Step 4: Run test to verify it passes**

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_packaging_inference.py -k "ai_" -q
```
Expected: PASS.

**Step 5: Commit**

```bash
git add src/bpg/providers/ai/base.py src/bpg/providers/ai/openai.py src/bpg/providers/ai/google.py src/bpg/providers/ai/ollama.py tests/test_packaging_inference.py
git commit -m "test(ai): cover packaging requirements for all ai providers"
```

### Task 8: Update docs/spec and migration guidance

**Files:**
- Modify: `docs/guides/add_ai_step.md`
- Modify: `docs/bpg-spec.md`
- Modify: `manual/nodes/built-in-providers.md`
- Create: `docs/plans/completed/2026-03-04-ai-provider-split-migration-notes.md` (optional short migration note)

**Step 1: Write the failing test**

Use a doc-level check by searching for stale single-vendor-only guidance:

```bash
rg -n "provider:\\s*ai\\.llm|vendor:\\s*anthropic|ai\\.anthropic|ai\\.openai|ai\\.google|ai\\.ollama" docs manual
```
Expected: output shows old examples not yet migrated.

**Step 2: Run test to verify it fails**

Run the same `rg` and confirm docs are incomplete.

**Step 3: Write minimal implementation**

Update examples to show preferred provider IDs:

```yaml
provider: ai.openai
config_schema:
  model: string
  output_schema: object
```

Add compatibility note:

```text
`ai.llm` remains supported as a compatibility alias to Anthropic and will be deprecated in a future release.
```

**Step 4: Run test to verify it passes**

Run:
```bash
rg -n "ai\\.openai|ai\\.google|ai\\.ollama|ai\\.anthropic|compatibility alias" docs manual
```
Expected: new provider IDs and migration note present.

**Step 5: Commit**

```bash
git add docs/guides/add_ai_step.md docs/bpg-spec.md manual/nodes/built-in-providers.md docs/plans/completed/2026-03-04-ai-provider-split-migration-notes.md
git commit -m "docs(ai): document vendor-specific ai providers and ai.llm migration"
```

### Task 9: Full verification and cleanup

**Files:**
- Modify: `src/bpg/providers/ai.py` (only if compatibility cleanup needed)
- Modify: `tests/test_providers.py` (final de-dup cleanup)

**Step 1: Write the failing test**

Run full provider and packaging suites:

```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py tests/test_packaging_inference.py tests/test_cli_provider_describe.py -q
```
Expected: Any residual failures identify integration gaps.

**Step 2: Run test to verify it fails**

Run and capture remaining failures.

**Step 3: Write minimal implementation**

Fix only failing assertions/contracts. Keep `ai.llm` mapped to Anthropic class for backward compatibility.

**Step 4: Run test to verify it passes**

Run:
```bash
source .venv/bin/activate && uv run pytest tests/test_providers.py tests/test_packaging_inference.py tests/test_cli_provider_describe.py -q
```
Expected: PASS.

Then run broader safety pass:

```bash
source .venv/bin/activate && uv run pytest -q
```
Expected: PASS (or record unrelated pre-existing failures).

**Step 5: Commit**

```bash
git add src/bpg/providers tests/test_providers.py tests/test_packaging_inference.py tests/test_cli_provider_describe.py
git commit -m "test(ai): finalize multi-provider ai node support with compatibility alias"
```
