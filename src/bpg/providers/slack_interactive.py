"""Slack interactive provider for human-in-the-loop BPG nodes.

When invoked, this provider:
1. Posts a Slack message with interactive action buttons to the configured channel.
2. Saves a pending-interaction record to the state store.
3. Raises a LangGraph ``interrupt()`` to suspend the graph.

When the graph is resumed (via ``graph.invoke(Command(resume=response), ...)``):
4. ``interrupt()`` returns the response value.
5. The response is persisted to the state store for audit.
6. An ``ExecutionHandle`` carrying the response is returned.

The external Slack callback webhook should:
a. Parse the Slack interactive payload to extract the ``idempotency_key`` and
   the chosen action (approve/reject/…).
b. Call ``provider.save_response(idempotency_key, output)`` to store the response.
c. Resume the graph: ``graph.invoke(Command(resume=output), config={"configurable": {"thread_id": run_id}})``.

Helper ``SlackInteractiveProvider.parse_action(action_id)`` decodes the
idempotency-key prefix and action label from a Slack ``action_id``.
"""

from __future__ import annotations

import json
import urllib.request
from typing import Any, Callable, Dict, Optional

from langgraph.types import interrupt

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
    ProviderError,
)
from bpg.state.store import StateStore


# ---------------------------------------------------------------------------
# Slack message builder
# ---------------------------------------------------------------------------

def _build_approval_blocks(
    input_payload: Dict[str, Any],
    buttons: list[str],
    idempotency_key: str,
) -> list[dict]:
    """Build Slack Block Kit blocks for an approval message."""
    title = input_payload.get("title", "Approval required")

    elements = []
    for label in buttons:
        action_id = f"bpg__{idempotency_key}__{label.lower()}"
        element: dict = {
            "type": "button",
            "text": {"type": "plain_text", "text": label},
            "action_id": action_id,
            "value": label.lower(),
        }
        if label.lower() in ("approve", "yes"):
            element["style"] = "primary"
        elif label.lower() in ("reject", "no", "deny"):
            element["style"] = "danger"
        elements.append(element)

    blocks: list[dict] = [
        {"type": "section", "text": {"type": "mrkdwn", "text": f"*{title}*"}},
    ]

    fields = [
        {"type": "mrkdwn", "text": f"*{k.replace('_', ' ').title()}:* {v}"}
        for k, v in input_payload.items()
        if k != "title" and v is not None
    ]
    if fields:
        blocks.append({"type": "section", "fields": fields[:10]})

    blocks.append({
        "type": "actions",
        "block_id": f"bpg_actions__{idempotency_key[:16]}",
        "elements": elements,
    })
    return blocks


def _post_slack_message(
    token: str,
    channel: str,
    input_payload: Dict[str, Any],
    buttons: list[str],
    idempotency_key: str,
) -> str:
    """Post an interactive approval message to Slack; return the message timestamp.

    Raises:
        ProviderError: If the Slack API returns an error.
    """
    blocks = _build_approval_blocks(input_payload, buttons, idempotency_key)
    body = json.dumps({
        "channel": channel,
        "blocks": blocks,
        "text": input_payload.get("title", "Approval required"),
    }).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            result = json.loads(resp.read())
    except Exception as exc:
        raise ProviderError(code="slack_http_error", message=str(exc), retryable=True)

    if not result.get("ok"):
        raise ProviderError(
            code="slack_api_error",
            message=result.get("error", "Unknown Slack error"),
            retryable=True,
        )
    return result["message"]["ts"]


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------

class SlackInteractiveProvider(Provider):
    """Provider for human-in-the-loop Slack approval nodes.

    Args:
        store: The BPG state store used to persist interaction records.
        bot_token: Slack bot OAuth token (``xoxb-…``).  May be empty for
            testing when a custom ``post_fn`` is supplied.
        post_fn: Optional injectable Slack posting function with the signature
            ``(token, channel, input_payload, buttons, idempotency_key) -> message_ts``.
            Defaults to the real ``_post_slack_message`` implementation.
            Pass a fake in tests to avoid real Slack API calls.
    """

    provider_id = "slack.interactive"

    def __init__(
        self,
        store: Optional[StateStore] = None,
        bot_token: str = "",
        *,
        post_fn: Optional[Callable[..., str]] = None,
    ) -> None:
        self._store = store
        self._token = bot_token
        self._post_fn: Callable[..., str] = post_fn or _post_slack_message

    # ------------------------------------------------------------------
    # Provider contract
    # ------------------------------------------------------------------

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        """Post a Slack message (first call) then suspend via ``interrupt()``.

        On LangGraph graph resume, ``interrupt()`` returns the value supplied
        to ``Command(resume=…)``.  That value is the human response payload.
        """
        key = context.idempotency_key
        channel: str = config.get("channel", "#general")
        buttons: list[str] = config.get("buttons") or ["Approve", "Reject"]

        # Post the Slack message only once (idempotent — skip if already sent).
        pending = self._store.load_pending_interaction(key) if self._store else None
        if pending is None:
            message_ts = self._post_fn(
                self._token, channel, input, buttons, key
            )
            if self._store:
                self._store.save_pending_interaction(key, {
                    "run_id": context.run_id,
                    "node_name": context.node_name,
                    "process_name": context.process_name,
                    "channel": channel,
                    "message_ts": message_ts,
                    "input": input,
                })

        # Suspend the graph until a human responds via the callback webhook.
        # On resume, ``interrupt()`` returns the value passed to Command(resume=…).
        response: Dict[str, Any] = interrupt({
            "type": "slack_approval",
            "idempotency_key": key,
            "channel": channel,
        })

        # Persist the response for audit / observability.
        if self._store:
            self._store.save_interaction_response(key, response)

        return ExecutionHandle(
            handle_id=key,
            idempotency_key=key,
            provider_id=self.provider_id,
            provider_data={"result": response},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        if handle.provider_data.get("result") is not None:
            return ExecutionStatus.COMPLETED
        if self._store:
            stored = self._store.load_interaction_response(handle.idempotency_key)
            return ExecutionStatus.COMPLETED if stored else ExecutionStatus.RUNNING
        return ExecutionStatus.RUNNING

    def await_result(
        self,
        handle: ExecutionHandle,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Return the human response payload stored in the handle."""
        result = handle.provider_data.get("result")
        if result is not None:
            return result
        # Fallback: check store (handles cases where provider_data was not set)
        if self._store:
            stored = self._store.load_interaction_response(handle.idempotency_key)
            if stored is not None:
                return stored
        raise ProviderError(
            code="no_response",
            message="No human response available for this interaction.",
            retryable=False,
        )

    def cancel(self, handle: ExecutionHandle) -> None:
        """No-op: Slack messages are not retracted on cancellation."""

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        _ = config
        return {
            "services": [],
            "required_env": ["SLACK_BOT_TOKEN"],
            "optional_env": ["SLACK_SIGNING_SECRET"],
        }

    def save_response(self, idempotency_key: str, output: Dict[str, Any]) -> None:
        """Persist the human response; call this from the Slack callback webhook.

        This must be called before resuming the graph so that the response is
        durable even if the resume fails and must be retried.

        Args:
            idempotency_key: The key embedded in the Slack action_id.
            output: The human response payload (e.g. ``{"approved": True}``).
        """
        self._store.save_interaction_response(idempotency_key, output)

    # ------------------------------------------------------------------
    # Slack callback helpers
    # ------------------------------------------------------------------

    @staticmethod
    def parse_action(action_id: str) -> tuple[str, str]:
        """Decode a BPG Slack action ID into (idempotency_key, action_label).

        Action IDs have the form ``bpg__<idempotency_key>__<label>``.

        Args:
            action_id: The ``action_id`` string from the Slack interactive payload.

        Returns:
            A ``(idempotency_key, action_label)`` tuple.

        Raises:
            ValueError: If ``action_id`` is not a valid BPG action ID.
        """
        parts = action_id.split("__")
        if len(parts) != 3 or parts[0] != "bpg":
            raise ValueError(f"Not a BPG action_id: {action_id!r}")
        return parts[1], parts[2]

    @staticmethod
    def action_to_output(action_label: str) -> Dict[str, Any]:
        """Convert an action label to the ApprovalDecision output schema.

        Maps ``approve``/``yes`` → ``{"approved": True}``,
        everything else → ``{"approved": False}``.

        Args:
            action_label: Lowercase action label from ``parse_action``.

        Returns:
            Output dict conforming to the ``ApprovalDecision`` schema.
        """
        approved = action_label in ("approve", "yes")
        return {"approved": approved, "reason": None}
