from __future__ import annotations

from typing import Any, Dict

from bpg.providers.base import ExecutionContext, ProviderError
from bpg.providers.ai.base import BaseAiProvider, _float_or_default, _int_or_default


class AiOpenAIProvider(BaseAiProvider):
    provider_id = "ai.openai"
    provider_description = "Structured-output LLM provider backed by OpenAI."
    default_api_key_env = "OPENAI_API_KEY"
    default_base_url = "https://api.openai.com/v1/responses"

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
        max_tokens = _int_or_default(config.get("max_tokens"), 1024, "config.max_tokens", self.provider_id)
        temperature = _float_or_default(config.get("temperature"), 0.0, "config.temperature", self.provider_id)
        system_prompt = str(config.get("system_prompt", "")).strip()

        payload: Dict[str, Any] = {
            "model": model,
            "input": [{"role": "user", "content": [{"type": "input_text", "text": prompt}]}],
            "temperature": temperature,
            "max_output_tokens": max_tokens,
        }
        if system_prompt:
            payload["instructions"] = system_prompt

        return self._http_post_json(
            endpoint=endpoint,
            payload=payload,
            headers={
                "content-type": "application/json",
                "authorization": f"Bearer {api_key}",
                "x-idempotency-key": context.idempotency_key,
            },
            error_label="openai",
        )

    def _extract_text(self, response: Dict[str, Any]) -> str:
        output_text = response.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text.strip()

        output = response.get("output")
        if not isinstance(output, list):
            raise ProviderError(
                code="llm_invalid_response",
                message="openai response missing output text",
                retryable=False,
            )

        parts: list[str] = []
        for item in output:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") in {"output_text", "text"} and isinstance(part.get("text"), str):
                    parts.append(part["text"])

        text = "\n".join(parts).strip()
        if not text:
            raise ProviderError(
                code="llm_invalid_response",
                message="openai response did not include text content",
                retryable=False,
            )
        return text
