"""Communication and integration BPG nodes (email, HTTP, Kafka, Slack)."""

from __future__ import annotations

import hashlib
import json
import os
import smtplib
import urllib.request
from email.message import EmailMessage
from typing import Any

from bpg_sdk import node
from bpg_sdk.manifest import Idempotency, ObservabilitySupport, RetrySafety, SideEffects

_PKG = "bpg.nodes.comm@v1"


def _is_dry_run(payload: dict[str, Any]) -> bool:
    raw = payload.get("dry_run")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    mode = os.getenv("BPG_EXECUTION_MODE", "").strip().lower()
    if mode in {"dry-run", "dry_run"}:
        return True
    return os.getenv("BPG_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}


def _node_key(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@node(
    package=_PKG,
    node_id="notify.email",
    input_schema={
        "type": "object",
        "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
            "from_addr": {"type": "string"},
            "smtp_host": {"type": "string"},
            "smtp_port": {"type": "integer"},
            "dry_run": {"type": "boolean"},
        },
        "required": ["to", "subject", "body"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "sent": {"type": "boolean"},
            "dry_run": {"type": "boolean"},
            "to": {"type": "string"},
            "from": {"type": "string"},
            "subject": {"type": "string"},
            "message_id": {"type": "string"},
        },
    },
    capabilities=["email"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
)
def notify_email(payload: dict[str, Any]) -> dict[str, Any]:
    to_addr = payload.get("to")
    subject = payload.get("subject")
    body = payload.get("body")
    if not isinstance(to_addr, str) or "@" not in to_addr:
        raise ValueError("notify.email requires to as an email address")
    if not isinstance(subject, str):
        raise ValueError("notify.email requires subject as a string")
    if not isinstance(body, str):
        raise ValueError("notify.email requires body as a string")

    from_addr = payload.get("from_addr") or payload.get("from") or os.getenv("SMTP_FROM")
    if not isinstance(from_addr, str) or "@" not in from_addr:
        raise ValueError("notify.email requires from_addr or SMTP_FROM")

    node_key = _node_key({"to": to_addr, "subject": subject, "body": body})

    if _is_dry_run(payload):
        return {
            "sent": False,
            "dry_run": True,
            "to": to_addr,
            "from": from_addr,
            "subject": subject,
            "message_id": f"dry-{node_key[:16]}",
        }

    host = payload.get("smtp_host") or os.getenv("SMTP_HOST")
    if not isinstance(host, str) or not host.strip():
        raise ValueError("notify.email requires smtp_host or SMTP_HOST in live mode")

    port_raw = payload.get("smtp_port", os.getenv("SMTP_PORT", "587"))
    try:
        port = int(port_raw)
    except (TypeError, ValueError):
        raise ValueError("notify.email SMTP port must be an integer")

    username = payload.get("smtp_username") or os.getenv("SMTP_USERNAME")
    password = payload.get("smtp_password") or os.getenv("SMTP_PASSWORD")
    starttls = bool(payload.get("smtp_starttls", True))

    msg = EmailMessage()
    msg["From"] = from_addr
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        with smtplib.SMTP(host=host, port=port, timeout=10) as client:
            if starttls:
                client.starttls()
            if username:
                client.login(username, password or "")
            client.send_message(msg)
    except Exception as exc:
        raise OSError(f"notify.email SMTP send error: {exc}") from exc

    return {
        "sent": True,
        "dry_run": False,
        "to": to_addr,
        "from": from_addr,
        "subject": subject,
        "message_id": f"smtp-{node_key[:16]}",
    }


@node(
    package=_PKG,
    node_id="http.gitlab",
    input_schema={
        "type": "object",
        "properties": {
            "ticket_prefix": {"type": "string"},
            "ticket_id": {"type": "string"},
            "issue_url": {"type": "string"},
            "labels": {"type": "array"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "ticket_id": {"type": "string"},
            "url": {"type": "string"},
        },
    },
    capabilities=["integration"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.SAFE,
)
def http_gitlab(payload: dict[str, Any]) -> dict[str, Any]:
    prefix = str(payload.get("ticket_prefix", "BPG"))
    node_key = _node_key(payload)
    issue_num = int(hashlib.sha256(node_key.encode()).hexdigest()[:8], 16) % 100000
    ticket_id = payload.get("ticket_id") or f"{prefix}-{issue_num:05d}"
    output: dict[str, Any] = {
        "ticket_id": ticket_id,
        "url": str(payload.get("issue_url", f"https://gitlab.local/issues/{ticket_id}")),
    }
    if isinstance(payload.get("labels"), list):
        output["labels"] = payload["labels"]
    return output


@node(
    package=_PKG,
    node_id="queue.kafka",
    input_schema={
        "type": "object",
        "properties": {
            "topic": {"type": "string"},
            "partition": {"type": "integer"},
            "offset": {"type": "integer"},
        },
        "required": ["topic"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "published": {"type": "boolean"},
            "topic": {"type": "string"},
            "partition": {"type": "integer"},
            "offset": {"type": "integer"},
        },
    },
    capabilities=["queue"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
)
def queue_kafka(payload: dict[str, Any]) -> dict[str, Any]:
    topic = payload.get("topic")
    if not topic:
        raise ValueError("queue.kafka requires topic")
    return {
        "published": True,
        "topic": str(topic),
        "partition": int(payload.get("partition", 0)),
        "offset": int(payload.get("offset", 0)),
    }


@node(
    package=_PKG,
    node_id="slack.interactive",
    input_schema={
        "type": "object",
        "properties": {
            "channel": {"type": "string"},
            "buttons": {"type": "array"},
            "bot_token_env": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {
            "dispatched": {"type": "boolean"},
            "channel": {"type": "string"},
            "message_ts": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
    },
    capabilities=["human-in-the-loop", "slack"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
    observability=ObservabilitySupport.REQUIRED,
)
def slack_interactive(payload: dict[str, Any]) -> dict[str, Any]:
    # In the v2 Temporal system, human-in-the-loop suspension is handled at
    # the workflow level. This node dispatches the Slack message and returns
    # dispatch metadata; the framework handles the wait-for-response cycle.
    channel = str(payload.get("channel", "#general"))
    node_key = _node_key(payload)

    if _is_dry_run(payload):
        return {
            "dispatched": True,
            "channel": channel,
            "message_ts": f"dry-{node_key[:16]}",
            "dry_run": True,
        }

    bot_token_env = str(payload.get("bot_token_env", "SLACK_BOT_TOKEN"))
    bot_token = os.getenv(bot_token_env)
    if not bot_token:
        raise ValueError(f"slack.interactive requires {bot_token_env}")

    buttons = payload.get("buttons") or ["Approve", "Reject"]
    blocks = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": "Human approval required"},
        },
        {
            "type": "actions",
            "elements": [
                {"type": "button", "text": {"type": "plain_text", "text": str(b)}, "value": str(b)}
                for b in buttons
            ],
        },
    ]
    slack_payload = json.dumps({"channel": channel, "blocks": blocks}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=slack_payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {bot_token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise OSError(f"slack.interactive Slack API error: {exc}") from exc

    if not response_data.get("ok"):
        raise ValueError(f"slack.interactive Slack error: {response_data.get('error')}")

    return {
        "dispatched": True,
        "channel": channel,
        "message_ts": str(response_data.get("ts", "")),
        "dry_run": False,
    }


@node(
    package=_PKG,
    node_id="http.webhook",
    input_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "headers": {"type": "object"},
            "async_mode": {"type": "boolean"},
        },
        "required": ["url"],
    },
    output_schema={"type": "object"},
    capabilities=["http"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
)
def http_webhook(payload: dict[str, Any]) -> dict[str, Any]:
    url = payload.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("http.webhook requires url")

    extra_headers: dict[str, str] = payload.get("headers") or {}
    body_payload = {k: v for k, v in payload.items() if k not in {"url", "headers", "async_mode"}}
    body = json.dumps(body_payload, sort_keys=True).encode()
    headers = {"Content-Type": "application/json", **extra_headers}

    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_body = json.loads(resp.read().decode("utf-8"))
    except Exception as exc:
        raise OSError(f"http.webhook POST error: {exc}") from exc

    return dict(response_body) if isinstance(response_body, dict) else {"response": response_body}


__all__ = [
    "notify_email",
    "http_gitlab",
    "queue_kafka",
    "slack_interactive",
    "http_webhook",
]
