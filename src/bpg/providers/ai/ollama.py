from __future__ import annotations

from typing import Any, Dict

from bpg.providers.base import ExecutionContext, ProviderError
from bpg.providers.ai.base import BaseAiProvider, _float_or_default, _int_or_default


class AiOllamaProvider(BaseAiProvider):
    provider_id = "ai.ollama"
    provider_description = "Structured-output LLM provider backed by Ollama."
    default_api_key_env = ""
    default_base_url = "http://localhost:11434/api/generate"

    def _call_model(
        self,
        *,
        model: str,
        prompt: str,
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        endpoint = self._base_url(config)
        max_tokens = _int_or_default(config.get("max_tokens"), 1024, "config.max_tokens", self.provider_id)
        temperature = _float_or_default(config.get("temperature"), 0.0, "config.temperature", self.provider_id)
        system_prompt = str(config.get("system_prompt", "")).strip()

        payload: Dict[str, Any] = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if system_prompt:
            payload["system"] = system_prompt

        return self._http_post_json(
            endpoint=endpoint,
            payload=payload,
            headers={
                "content-type": "application/json",
                "x-idempotency-key": context.idempotency_key,
            },
            error_label="ollama",
        )

    def _extract_text(self, response: Dict[str, Any]) -> str:
        text = response.get("response")
        if not isinstance(text, str) or not text.strip():
            raise ProviderError(
                code="llm_invalid_response",
                message="ollama response missing response text",
                retryable=False,
            )
        return text.strip()
