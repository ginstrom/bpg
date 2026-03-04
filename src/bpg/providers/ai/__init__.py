"""AI provider implementations."""

from bpg.providers.ai.anthropic import AiAnthropicProvider
from bpg.providers.ai.google import AiGoogleProvider
from bpg.providers.ai.ollama import AiOllamaProvider
from bpg.providers.ai.openai import AiOpenAIProvider


class AiLlmProvider(AiAnthropicProvider):
    """Compatibility alias for legacy `ai.llm` provider id."""

    provider_id = "ai.llm"
    provider_description = (
        "Compatibility alias for ai.anthropic. Prefer ai.anthropic, ai.openai, ai.google, or ai.ollama."
    )


__all__ = [
    "AiAnthropicProvider",
    "AiOpenAIProvider",
    "AiGoogleProvider",
    "AiOllamaProvider",
    "AiLlmProvider",
]
