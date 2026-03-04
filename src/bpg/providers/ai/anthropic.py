from __future__ import annotations

from typing import Any, Dict

from bpg.providers.base import ExecutionContext, ProviderError
from bpg.providers.ai.base import BaseAiProvider, _float_or_default, _int_or_default


class AiAnthropicProvider(BaseAiProvider):
    provider_id = "ai.anthropic"
    provider_description = "Structured-output LLM provider backed by Anthropic."
    default_api_key_env = "ANTHROPIC_API_KEY"
    default_base_url = "https://api.anthropic.com/v1/messages"

    def _call_model(
        self,
        *,
        model: str,
        prompt: str,
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        api_key = self._read_api_key(config)
        endpoint = self._base_url(config)
        anthropic_version = str(config.get("anthropic_version", "2023-06-01"))
        max_tokens = _int_or_default(config.get("max_tokens"), 1024, "config.max_tokens", self.provider_id)
        temperature = _float_or_default(config.get("temperature"), 0.0, "config.temperature", self.provider_id)
        system_prompt = str(config.get("system_prompt", "")).strip()

        payload: Dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system_prompt:
            payload["system"] = system_prompt

        response = self._http_post_json(
            endpoint=endpoint,
            payload=payload,
            headers={
                "content-type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": anthropic_version,
                "x-idempotency-key": context.idempotency_key,
            },
            error_label="anthropic",
        )
        if response.get("type") == "error":
            err = response.get("error") if isinstance(response.get("error"), dict) else {}
            raise ProviderError(
                code="llm_http_error",
                message=f"anthropic error: {err.get('message', 'unknown error')}",
                retryable=False,
            )
        return response

    def _extract_text(self, response: Dict[str, Any]) -> str:
        content = response.get("content")
        if not isinstance(content, list):
            raise ProviderError(
                code="llm_invalid_response",
                message="anthropic response missing content array",
                retryable=False,
            )
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text" and isinstance(item.get("text"), str):
                parts.append(item["text"])
        text = "\n".join(parts).strip()
        if not text:
            raise ProviderError(
                code="llm_invalid_response",
                message="anthropic response did not include text content",
                retryable=False,
            )
        return text
