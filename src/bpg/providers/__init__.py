"""BPG provider layer — pluggable execution backends.

All providers implement the contract defined in §3.3 of the spec:

    invoke(input, config, context) -> ExecutionHandle
    poll(handle)                   -> ExecutionStatus
    await_(handle, timeout)        -> TypedOutput
    cancel(handle)                 -> None

Idempotency (§8)
----------------
Every invoke call is keyed before reaching the provider.  Callers use
``compute_idempotency_key`` to derive the key and embed it in an
``ExecutionContext`` before calling ``Provider.invoke``.

Public API
----------
    Provider                — Abstract base class for all providers
    ExecutionHandle         — Opaque handle returned by invoke
    ExecutionStatus         — Running / Completed / Failed
    ExecutionContext         — Runtime context (run_id, node_name, key, ...)
    ProviderError           — Typed error (code, message, retryable)
    compute_idempotency_key — SHA-256(run_id:node_name:canonical_json(input))
    PROVIDER_REGISTRY       — Maps provider ID strings → implementation classes

Built-in provider IDs (§3.3)
-----------------------------
    mock          — Canned-output provider for testing
    http.webhook  — Generic HTTP webhook (sync or async poll)
"""

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
    ProviderError,
    compute_idempotency_key,
)
from bpg.providers.mock import MockProvider
from bpg.providers.webhook import WebhookProvider
from bpg.providers.slack_interactive import SlackInteractiveProvider
from bpg.providers.core import DatasetSelectProvider, PassthroughProvider
from bpg.providers.ai import (
    AiAnthropicProvider,
    AiGoogleProvider,
    AiLlmProvider,
    AiOllamaProvider,
    AiOpenAIProvider,
)
from bpg.providers.builtin import (
    AgentPipelineProvider,
    BpgProcessCallProvider,
    DashboardFormProvider,
    EmbedTextProvider,
    EmailNotifyProvider,
    FlowAwaitAllProvider,
    FlowFanoutProvider,
    FlowLoopProvider,
    HttpGitlabProvider,
    MarkdownChunkProvider,
    MarkdownListProvider,
    ParseTextNumbersProvider,
    QueueKafkaProvider,
    SumNumbersProvider,
    TimerDelayProvider,
    WeaviateHybridSearchProvider,
    WeaviateUpsertProvider,
    WebSearchProvider,
)
from bpg.providers.metadata import ProviderMetadata


__all__ = [
    "Provider",
    "ExecutionHandle",
    "ExecutionStatus",
    "ExecutionContext",
    "ProviderError",
    "compute_idempotency_key",
    "MockProvider",
    "WebhookProvider",
    "AiAnthropicProvider",
    "AiOpenAIProvider",
    "AiGoogleProvider",
    "AiOllamaProvider",
    "SlackInteractiveProvider",
    "AiLlmProvider",
    "DatasetSelectProvider",
    "AgentPipelineProvider",
    "DashboardFormProvider",
    "MarkdownListProvider",
    "MarkdownChunkProvider",
    "EmbedTextProvider",
    "WeaviateUpsertProvider",
    "WeaviateHybridSearchProvider",
    "EmailNotifyProvider",
    "HttpGitlabProvider",
    "QueueKafkaProvider",
    "TimerDelayProvider",
    "FlowLoopProvider",
    "FlowFanoutProvider",
    "FlowAwaitAllProvider",
    "BpgProcessCallProvider",
    "ParseTextNumbersProvider",
    "SumNumbersProvider",
    "WebSearchProvider",
    "PROVIDER_REGISTRY",
    "ProviderMetadata",
    "list_provider_metadata",
    "describe_provider_metadata",
]

PROVIDER_REGISTRY: dict[str, type[Provider]] = {
    MockProvider.provider_id: MockProvider,
    WebhookProvider.provider_id: WebhookProvider,
    SlackInteractiveProvider.provider_id: SlackInteractiveProvider,
    AiAnthropicProvider.provider_id: AiAnthropicProvider,
    AiOpenAIProvider.provider_id: AiOpenAIProvider,
    AiGoogleProvider.provider_id: AiGoogleProvider,
    AiOllamaProvider.provider_id: AiOllamaProvider,
    AiLlmProvider.provider_id: AiLlmProvider,
    PassthroughProvider.provider_id: PassthroughProvider,
    DatasetSelectProvider.provider_id: DatasetSelectProvider,
    AgentPipelineProvider.provider_id: AgentPipelineProvider,
    DashboardFormProvider.provider_id: DashboardFormProvider,
    HttpGitlabProvider.provider_id: HttpGitlabProvider,
    TimerDelayProvider.provider_id: TimerDelayProvider,
    QueueKafkaProvider.provider_id: QueueKafkaProvider,
    FlowLoopProvider.provider_id: FlowLoopProvider,
    FlowFanoutProvider.provider_id: FlowFanoutProvider,
    FlowAwaitAllProvider.provider_id: FlowAwaitAllProvider,
    BpgProcessCallProvider.provider_id: BpgProcessCallProvider,
    ParseTextNumbersProvider.provider_id: ParseTextNumbersProvider,
    SumNumbersProvider.provider_id: SumNumbersProvider,
    MarkdownListProvider.provider_id: MarkdownListProvider,
    MarkdownChunkProvider.provider_id: MarkdownChunkProvider,
    EmbedTextProvider.provider_id: EmbedTextProvider,
    WeaviateUpsertProvider.provider_id: WeaviateUpsertProvider,
    WeaviateHybridSearchProvider.provider_id: WeaviateHybridSearchProvider,
    WebSearchProvider.provider_id: WebSearchProvider,
    EmailNotifyProvider.provider_id: EmailNotifyProvider,
}
"""Maps provider ID strings to their implementation classes.

Example::

    provider_cls = PROVIDER_REGISTRY["http.webhook"]
    provider = provider_cls()
    handle = provider.invoke(input, config, context)
"""


def list_provider_metadata() -> list[ProviderMetadata]:
    """Return metadata for every registered provider in deterministic order."""
    items: list[ProviderMetadata] = []
    for provider_id in sorted(PROVIDER_REGISTRY):
        items.append(PROVIDER_REGISTRY[provider_id].metadata())
    return items


def describe_provider_metadata(provider_id: str) -> ProviderMetadata:
    """Return metadata for a provider ID or raise KeyError."""
    provider_cls = PROVIDER_REGISTRY[provider_id]
    return provider_cls.metadata()
