"""BPG provider layer — pluggable execution backends.

All providers implement the contract defined in §3.3 of the spec:

    invoke(input, config, context) -> ExecutionHandle
    poll(handle)                   -> ExecutionStatus
    await_result(handle, timeout)  -> TypedOutput
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

from typing import ClassVar

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


class _StubProvider(Provider):
    """Base stub for built-in providers without a real implementation.

    Raises an informative ProviderError on invoke. Used so that ``bpg apply``
    can deploy nodes of these types (deploy() is a no-op) without crashing,
    while failing clearly at runtime if no real provider is substituted.
    """

    provider_id: ClassVar[str] = ""

    def invoke(self, input, config, context):
        raise ProviderError(
            code="not_implemented",
            message=(
                f"Provider '{self.provider_id}' has no built-in implementation. "
                "Register a custom provider in your runtime configuration."
            ),
            retryable=False,
        )

    def poll(self, handle):
        return ExecutionStatus.FAILED

    def await_result(self, handle, timeout=None):
        raise ProviderError(
            code="not_implemented",
            message=f"Provider '{self.provider_id}' not implemented.",
            retryable=False,
        )

    def cancel(self, handle):
        pass


def _make_stub(pid: str) -> type[Provider]:
    """Dynamically create a named stub provider class for a given provider ID."""
    return type(f"_Stub_{pid.replace('.', '_')}", (_StubProvider,), {"provider_id": pid})


_AgentPipelineProvider = _make_stub("agent.pipeline")
_DashboardFormProvider = _make_stub("dashboard.form")
_HttpGitlabProvider = _make_stub("http.gitlab")
_TimerDelayProvider = _make_stub("timer.delay")
_QueueKafkaProvider = _make_stub("queue.kafka")


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
    "PROVIDER_REGISTRY",
]

PROVIDER_REGISTRY: dict[str, type[Provider]] = {
    MockProvider.provider_id: MockProvider,
    WebhookProvider.provider_id: WebhookProvider,
    SlackInteractiveProvider.provider_id: SlackInteractiveProvider,
    _AgentPipelineProvider.provider_id: _AgentPipelineProvider,
    _DashboardFormProvider.provider_id: _DashboardFormProvider,
    _HttpGitlabProvider.provider_id: _HttpGitlabProvider,
    _TimerDelayProvider.provider_id: _TimerDelayProvider,
    _QueueKafkaProvider.provider_id: _QueueKafkaProvider,
}
"""Maps provider ID strings to their implementation classes.

Example::

    provider_cls = PROVIDER_REGISTRY["http.webhook"]
    provider = provider_cls()
    handle = provider.invoke(input, config, context)
"""
