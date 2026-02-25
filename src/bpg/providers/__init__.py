"""BPG provider layer — pluggable execution backends.

All providers MUST implement the provider contract defined in §3.3:

    invoke(input, config, context) -> ExecutionHandle
    poll(handle) -> ExecutionStatus
    await(handle, timeout) -> TypedOutput
    cancel(handle) -> None

Providers MUST:
    - Accept and honor idempotency keys
    - Produce structured, schema-conformant output
    - Surface errors as typed ProviderError values, not exceptions
    - Be stateless with respect to process logic (all state lives in the runtime)

Built-in provider IDs (§3.3):
    agent.pipeline   — AI agent pipeline invocation
    slack.interactive — Interactive Slack approval messages
    dashboard.form   — Web form for structured human input
    http.webhook     — Generic HTTP webhook send/receive
    http.gitlab      — GitLab REST API operations
    queue.kafka      — Kafka publish/consume
    timer.delay      — Wait a specified duration
"""

# Provider implementations are registered here as they are built out.
# Example (once implemented):
#   from bpg.providers.agent_pipeline import AgentPipelineProvider
#   from bpg.providers.slack_interactive import SlackInteractiveProvider

PROVIDER_REGISTRY: dict[str, type] = {}
"""Maps provider ID strings to their implementation classes."""
