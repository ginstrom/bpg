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
from bpg.providers.core import PassthroughProvider
from bpg.providers.builtin import (
    AgentPipelineProvider,
    BpgProcessCallProvider,
    DashboardFormProvider,
    FlowAwaitAllProvider,
    FlowFanoutProvider,
    FlowLoopProvider,
    HttpGitlabProvider,
    QueueKafkaProvider,
    TimerDelayProvider,
)


__all__ = [
    "Provider",
    "ExecutionHandle",
    "ExecutionStatus",
    "ExecutionContext",
    "ProviderError",
    "compute_idempotency_key",
    "MockProvider",
    "WebhookProvider",
    "SlackInteractiveProvider",
    "AgentPipelineProvider",
    "DashboardFormProvider",
    "HttpGitlabProvider",
    "QueueKafkaProvider",
    "TimerDelayProvider",
    "FlowLoopProvider",
    "FlowFanoutProvider",
    "FlowAwaitAllProvider",
    "BpgProcessCallProvider",
    "PROVIDER_REGISTRY",
]

PROVIDER_REGISTRY: dict[str, type[Provider]] = {
    MockProvider.provider_id: MockProvider,
    WebhookProvider.provider_id: WebhookProvider,
    SlackInteractiveProvider.provider_id: SlackInteractiveProvider,
    PassthroughProvider.provider_id: PassthroughProvider,
    AgentPipelineProvider.provider_id: AgentPipelineProvider,
    DashboardFormProvider.provider_id: DashboardFormProvider,
    HttpGitlabProvider.provider_id: HttpGitlabProvider,
    TimerDelayProvider.provider_id: TimerDelayProvider,
    QueueKafkaProvider.provider_id: QueueKafkaProvider,
    FlowLoopProvider.provider_id: FlowLoopProvider,
    FlowFanoutProvider.provider_id: FlowFanoutProvider,
    FlowAwaitAllProvider.provider_id: FlowAwaitAllProvider,
    BpgProcessCallProvider.provider_id: BpgProcessCallProvider,
}
"""Maps provider ID strings to their implementation classes.

Example::

    provider_cls = PROVIDER_REGISTRY["http.webhook"]
    provider = provider_cls()
    handle = provider.invoke(input, config, context)
"""
