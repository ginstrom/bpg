from __future__ import annotations

from typing import Any, Dict

from bpg.providers.base import ExecutionContext, ProviderError
from bpg.providers.ai.base import BaseAiProvider, _float_or_default, _int_or_default, append_query_params


class AiGoogleProvider(BaseAiProvider):
    provider_id = "ai.google"
    provider_description = "Structured-output LLM provider backed by Google Gemini API."
    default_api_key_env = "GOOGLE_API_KEY"
    default_base_url = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    def _call_model(
        self,
        *,
        model: str,
        prompt: str,
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        api_key = self._read_api_key(config)
        endpoint_tmpl = self._base_url(config)
        endpoint = endpoint_tmpl.format(model=model)
        endpoint = append_query_params(endpoint, {"key": api_key})
        max_tokens = _int_or_default(config.get("max_tokens"), 1024, "config.max_tokens", self.provider_id)
        temperature = _float_or_default(config.get("temperature"), 0.0, "config.temperature", self.provider_id)
        system_prompt = str(config.get("system_prompt", "")).strip()

        payload: Dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
        }
        if system_prompt:
            payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

        return self._http_post_json(
            endpoint=endpoint,
            payload=payload,
            headers={
                "content-type": "application/json",
                "x-idempotency-key": context.idempotency_key,
            },
            error_label="google",
        )

    def _extract_text(self, response: Dict[str, Any]) -> str:
        candidates = response.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            raise ProviderError(
                code="llm_invalid_response",
                message="google response missing candidates",
                retryable=False,
            )

        first = candidates[0]
        if not isinstance(first, dict):
            raise ProviderError(
                code="llm_invalid_response",
                message="google response candidate format invalid",
                retryable=False,
            )

        content = first.get("content")
        if not isinstance(content, dict):
            raise ProviderError(
                code="llm_invalid_response",
                message="google response missing candidate content",
                retryable=False,
            )

        parts = content.get("parts")
        if not isinstance(parts, list):
            raise ProviderError(
                code="llm_invalid_response",
                message="google response missing content parts",
                retryable=False,
            )

        text_parts: list[str] = []
        for item in parts:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                text_parts.append(item["text"])
        text = "\n".join(text_parts).strip()
        if not text:
            raise ProviderError(
                code="llm_invalid_response",
                message="google response did not include text content",
                retryable=False,
            )
        return text
