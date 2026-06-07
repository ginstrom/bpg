"""Optional audit reporting and compliance helper nodes for BPG."""

from __future__ import annotations

import hashlib
import json
import os
import smtplib
import urllib.request
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Mapping

from bpg.audit.inspection import (
    AuditSinkResolutionError,
    build_audit_export_bundle,
    build_trace_summary,
    fetch_run_audit_rows,
    resolve_audit_sink as _default_resolve_audit_sink,
    verification_to_dict,
    verify_run_audit_chain,
    write_audit_export_bundle,
)

resolve_audit_sink = _default_resolve_audit_sink
from bpg_sdk import node
from bpg_sdk.manifest import Idempotency, ObservabilitySupport, RetrySafety, SideEffects

_PKG = "bpg.nodes.audit@v1"
_CORE_AUDIT_LIFECYCLE_EVENTS = frozenset(
    {
        "run_started",
        "run_completed",
        "run_failed",
        "node_scheduled",
        "node_started",
        "node_completed",
        "node_failed",
        "node_skipped",
        "node_retry_scheduled",
        "edge_fired",
        "policy_checked",
        "policy_blocked",
        "approval_requested",
        "approval_resolved",
        "approval_timed_out",
        "artifact_written",
        "audit_checkpointed",
    }
)


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


def _require_run_id(payload: dict[str, Any]) -> str:
    run_id = payload.get("run_id")
    if not isinstance(run_id, str) or not run_id.strip():
        raise ValueError("run_id is required")
    return run_id.strip()


def _resolve_sink(payload: dict[str, Any]):
    dsn = payload.get("dsn")
    dsn_env = payload.get("dsn_env")
    try:
        return resolve_audit_sink(
            dsn=str(dsn) if isinstance(dsn, str) and dsn.strip() else None,
            dsn_env=str(dsn_env) if isinstance(dsn_env, str) and dsn_env.strip() else None,
        )
    except AuditSinkResolutionError as exc:
        raise RuntimeError(str(exc)) from exc


def _event_type_counts(rows: list[Mapping[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        event_type = str(row.get("event_type") or "unknown")
        counts[event_type] = counts.get(event_type, 0) + 1
    return dict(sorted(counts.items()))


def _build_summary_text(
    *,
    run_id: str,
    rows: list[Mapping[str, Any]],
    verification: Mapping[str, Any],
    trace_summary: Mapping[str, Any],
    policy_tags: Mapping[str, Any] | None = None,
) -> str:
    lines = [
        f"# Compliance Summary: {run_id}",
        "",
        f"- Process: {rows[0].get('process_name')} ({rows[0].get('process_version')})",
        f"- Event count: {len(rows)}",
        f"- Hash chain valid: {verification.get('ok', False)}",
        f"- Trace ID: {trace_summary.get('trace_id') or 'n/a'}",
    ]
    if policy_tags:
        lines.append(f"- Policy tags: {json.dumps(dict(policy_tags), sort_keys=True)}")
    lines.extend(["", "## Event counts"])
    for event_type, count in _event_type_counts(rows).items():
        lines.append(f"- {event_type}: {count}")
    return "\n".join(lines) + "\n"


def _bundle_from_payload(payload: dict[str, Any], *, run_id: str) -> dict[str, Any]:
    bundle = payload.get("bundle")
    if isinstance(bundle, dict):
        return dict(bundle)
    sink = _resolve_sink(payload)
    return build_audit_export_bundle(
        sink,
        run_id,
        from_checkpoint=bool(payload.get("from_checkpoint", False)),
        require_anchor=bool(payload.get("require_anchor", False)),
    )


@node(
    package=_PKG,
    node_id="audit.export_bundle",
    input_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "output_path": {"type": "string"},
            "dsn": {"type": "string"},
            "dsn_env": {"type": "string"},
            "from_checkpoint": {"type": "boolean"},
            "require_anchor": {"type": "boolean"},
        },
        "required": ["run_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "exported": {"type": "boolean"},
            "output_path": {"type": "string"},
            "bundle": {"type": "object"},
            "event_count": {"type": "integer"},
            "verification_valid": {"type": "boolean"},
        },
        "required": ["run_id", "exported", "bundle", "event_count", "verification_valid"],
    },
    capabilities=["audit_logging", "evidence_export"],
    side_effects=SideEffects.READS,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
    observability=ObservabilitySupport.SUPPORTED,
)
def export_audit_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _require_run_id(payload)
    sink = _resolve_sink(payload)
    bundle = build_audit_export_bundle(
        sink,
        run_id,
        from_checkpoint=bool(payload.get("from_checkpoint", False)),
        require_anchor=bool(payload.get("require_anchor", False)),
    )
    output_path = payload.get("output_path")
    if isinstance(output_path, str) and output_path.strip():
        path = Path(output_path)
        write_audit_export_bundle(path, bundle)
        return {
            "run_id": run_id,
            "exported": True,
            "output_path": str(path),
            "bundle": bundle,
            "event_count": len(bundle.get("events", [])),
            "verification_valid": bool(bundle.get("verification", {}).get("ok")),
        }
    return {
        "run_id": run_id,
        "exported": False,
        "bundle": bundle,
        "event_count": len(bundle.get("events", [])),
        "verification_valid": bool(bundle.get("verification", {}).get("ok")),
    }


@node(
    package=_PKG,
    node_id="audit.verify_chain",
    input_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "dsn": {"type": "string"},
            "dsn_env": {"type": "string"},
            "from_checkpoint": {"type": "boolean"},
            "require_anchor": {"type": "boolean"},
        },
        "required": ["run_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "valid": {"type": "boolean"},
            "verification": {"type": "object"},
            "event_count": {"type": "integer"},
        },
        "required": ["run_id", "valid", "verification", "event_count"],
    },
    capabilities=["audit_logging", "audit_verification"],
    side_effects=SideEffects.READS,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def verify_audit_chain(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _require_run_id(payload)
    sink = _resolve_sink(payload)
    rows = fetch_run_audit_rows(sink, run_id)
    verification = verify_run_audit_chain(
        sink,
        run_id,
        from_checkpoint=bool(payload.get("from_checkpoint", False)),
        require_anchor=bool(payload.get("require_anchor", False)),
    )
    return {
        "run_id": run_id,
        "valid": verification.ok,
        "verification": verification_to_dict(verification),
        "event_count": len(rows),
    }


@node(
    package=_PKG,
    node_id="audit.write_compliance_summary",
    input_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "bundle": {"type": "object"},
            "format": {"type": "string", "enum": ["markdown", "json"]},
            "policy_tags": {"type": "object"},
            "dsn": {"type": "string"},
            "dsn_env": {"type": "string"},
            "from_checkpoint": {"type": "boolean"},
            "require_anchor": {"type": "boolean"},
        },
        "required": ["run_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "format": {"type": "string"},
            "summary": {},
            "event_count": {"type": "integer"},
            "verification_valid": {"type": "boolean"},
        },
        "required": ["run_id", "format", "summary", "event_count", "verification_valid"],
    },
    capabilities=["audit_logging", "compliance_reporting"],
    side_effects=SideEffects.READS,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def write_compliance_summary(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _require_run_id(payload)
    bundle = _bundle_from_payload(payload, run_id=run_id)
    rows = bundle.get("events") or []
    verification = bundle.get("verification") or {}
    trace_summary = build_trace_summary(rows)
    output_format = str(payload.get("format") or "markdown").strip().lower()
    policy_tags = payload.get("policy_tags") if isinstance(payload.get("policy_tags"), dict) else None

    if output_format == "json":
        summary: str | dict[str, Any] = {
            "run_id": run_id,
            "process_name": bundle.get("process_name"),
            "process_version": bundle.get("process_version"),
            "process_hash": bundle.get("process_hash"),
            "event_count": len(rows),
            "event_counts": _event_type_counts(rows),
            "verification": verification,
            "trace_summary": trace_summary,
            "policy_tags": dict(policy_tags or {}),
        }
    else:
        summary = _build_summary_text(
            run_id=run_id,
            rows=rows,
            verification=verification,
            trace_summary=trace_summary,
            policy_tags=policy_tags,
        )

    return {
        "run_id": run_id,
        "format": output_format,
        "summary": summary,
        "event_count": len(rows),
        "verification_valid": bool(verification.get("ok")),
    }


@node(
    package=_PKG,
    node_id="audit.notify_compliance_channel",
    input_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "channel": {"type": "string"},
            "channel_type": {"type": "string", "enum": ["slack", "email", "webhook"]},
            "summary": {"type": "string"},
            "webhook_url": {"type": "string"},
            "dsn": {"type": "string"},
            "dsn_env": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
        "required": ["run_id", "channel", "channel_type"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "notified": {"type": "boolean"},
            "channel": {"type": "string"},
            "channel_type": {"type": "string"},
            "dry_run": {"type": "boolean"},
            "delivery_ref": {"type": "string"},
        },
        "required": ["run_id", "notified", "channel", "channel_type", "dry_run"],
    },
    capabilities=["audit_logging", "compliance_reporting", "notification"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.NON_IDEMPOTENT,
    retry_safety=RetrySafety.CONDITIONAL,
)
def notify_compliance_channel(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _require_run_id(payload)
    channel = str(payload.get("channel") or "").strip()
    channel_type = str(payload.get("channel_type") or "").strip().lower()
    if not channel:
        raise ValueError("channel is required")
    if channel_type not in {"slack", "email", "webhook"}:
        raise ValueError("channel_type must be one of: slack, email, webhook")

    summary = payload.get("summary")
    if not isinstance(summary, str) or not summary.strip():
        summary_payload = write_compliance_summary({"run_id": run_id, **payload})
        rendered = summary_payload["summary"]
        summary = rendered if isinstance(rendered, str) else json.dumps(rendered, sort_keys=True)

    node_key = _node_key({"run_id": run_id, "channel": channel, "channel_type": channel_type})
    if _is_dry_run(payload):
        return {
            "run_id": run_id,
            "notified": False,
            "channel": channel,
            "channel_type": channel_type,
            "dry_run": True,
            "delivery_ref": f"dry-{node_key[:16]}",
        }

    if channel_type == "webhook":
        webhook_url = payload.get("webhook_url") or os.getenv("COMPLIANCE_WEBHOOK_URL")
        if not isinstance(webhook_url, str) or not webhook_url.strip():
            raise ValueError("webhook channel requires webhook_url or COMPLIANCE_WEBHOOK_URL")
        body = json.dumps(
            {"run_id": run_id, "channel": channel, "summary": summary},
            sort_keys=True,
        ).encode()
        req = urllib.request.Request(
            webhook_url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                resp.read()
        except Exception as exc:
            raise OSError(f"audit.notify_compliance_channel webhook error: {exc}") from exc
        return {
            "run_id": run_id,
            "notified": True,
            "channel": channel,
            "channel_type": channel_type,
            "dry_run": False,
            "delivery_ref": f"webhook-{node_key[:16]}",
        }

    if channel_type == "email":
        to_addr = channel
        from_addr = os.getenv("SMTP_FROM")
        if not isinstance(from_addr, str) or "@" not in from_addr:
            raise ValueError("email channel requires SMTP_FROM")
        host = os.getenv("SMTP_HOST")
        if not isinstance(host, str) or not host.strip():
            raise ValueError("email channel requires SMTP_HOST")
        port = int(os.getenv("SMTP_PORT", "587"))
        msg = EmailMessage()
        msg["From"] = from_addr
        msg["To"] = to_addr
        msg["Subject"] = f"Compliance summary for {run_id}"
        msg.set_content(summary)
        try:
            with smtplib.SMTP(host=host, port=port, timeout=10) as client:
                if os.getenv("SMTP_STARTTLS", "1").strip().lower() not in {"0", "false", "no"}:
                    client.starttls()
                username = os.getenv("SMTP_USERNAME")
                if username:
                    client.login(username, os.getenv("SMTP_PASSWORD") or "")
                client.send_message(msg)
        except Exception as exc:
            raise OSError(f"audit.notify_compliance_channel email error: {exc}") from exc
        return {
            "run_id": run_id,
            "notified": True,
            "channel": channel,
            "channel_type": channel_type,
            "dry_run": False,
            "delivery_ref": f"email-{node_key[:16]}",
        }

    bot_token = os.getenv("SLACK_BOT_TOKEN")
    if not bot_token:
        raise ValueError("slack channel requires SLACK_BOT_TOKEN")
    slack_payload = json.dumps(
        {"channel": channel, "text": summary},
        sort_keys=True,
    ).encode()
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
        raise OSError(f"audit.notify_compliance_channel slack error: {exc}") from exc
    if not response_data.get("ok"):
        raise ValueError(f"audit.notify_compliance_channel slack error: {response_data.get('error')}")
    return {
        "run_id": run_id,
        "notified": True,
        "channel": channel,
        "channel_type": channel_type,
        "dry_run": False,
        "delivery_ref": str(response_data.get("ts", f"slack-{node_key[:16]}")),
    }


@node(
    package=_PKG,
    node_id="audit.create_case",
    input_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "case_system": {"type": "string"},
            "title": {"type": "string"},
            "labels": {"type": "array", "items": {"type": "string"}},
            "dry_run": {"type": "boolean"},
        },
        "required": ["run_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "case_id": {"type": "string"},
            "url": {"type": "string"},
            "case_system": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
        "required": ["run_id", "case_id", "url", "case_system", "dry_run"],
    },
    capabilities=["audit_logging", "compliance_reporting", "integration"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.SAFE,
)
def create_audit_case(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _require_run_id(payload)
    case_system = str(payload.get("case_system") or "gitlab").strip().lower()
    title = str(payload.get("title") or f"Audit review for {run_id}")
    node_key = _node_key({"run_id": run_id, "case_system": case_system, "title": title})
    issue_num = int(hashlib.sha256(node_key.encode()).hexdigest()[:8], 16) % 100000
    case_id = f"AUDIT-{issue_num:05d}"
    url = f"https://{case_system}.local/compliance/{case_id}"
    labels = payload.get("labels")
    output: dict[str, Any] = {
        "run_id": run_id,
        "case_id": case_id,
        "url": url,
        "case_system": case_system,
        "dry_run": _is_dry_run(payload),
    }
    if isinstance(labels, list):
        output["labels"] = labels
    return output


@node(
    package=_PKG,
    node_id="audit.attach_evidence",
    input_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "case_id": {"type": "string"},
            "case_url": {"type": "string"},
            "bundle": {"type": "object"},
            "bundle_path": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
        "required": ["run_id", "case_id"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "run_id": {"type": "string"},
            "case_id": {"type": "string"},
            "attached": {"type": "boolean"},
            "evidence_ref": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
        "required": ["run_id", "case_id", "attached", "evidence_ref", "dry_run"],
    },
    capabilities=["audit_logging", "evidence_export", "integration"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.SAFE,
)
def attach_evidence_to_ticket(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = _require_run_id(payload)
    case_id = str(payload.get("case_id") or "").strip()
    if not case_id:
        raise ValueError("case_id is required")

    bundle_path = payload.get("bundle_path")
    bundle = payload.get("bundle")
    if isinstance(bundle_path, str) and bundle_path.strip():
        evidence_ref = bundle_path.strip()
    elif isinstance(bundle, dict):
        evidence_ref = hashlib.sha256(
            json.dumps(bundle, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()[:16]
    else:
        raise ValueError("attach_evidence requires bundle or bundle_path")

    return {
        "run_id": run_id,
        "case_id": case_id,
        "attached": not _is_dry_run(payload),
        "evidence_ref": evidence_ref,
        "dry_run": _is_dry_run(payload),
    }


__all__ = [
    "_CORE_AUDIT_LIFECYCLE_EVENTS",
    "attach_evidence_to_ticket",
    "create_audit_case",
    "export_audit_bundle",
    "notify_compliance_channel",
    "resolve_audit_sink",
    "verify_audit_chain",
    "write_compliance_summary",
]
