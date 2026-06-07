"""Audit policy parsing, redaction, and payload projection."""

from __future__ import annotations

from dataclasses import dataclass, field
import os
from typing import Any, Iterable, Literal, Mapping

from bpg.runtime.events import BpgEvent, sha256_json

AuditFailurePolicy = Literal["fail_run", "warn", "disabled"]
AuditPayloadRetention = Literal["hash_only", "redacted", "full"]
AuditSink = Literal["postgres"]
DuplicateStrategy = Literal["reject", "ignore"]

_AUDIT_FAILURE_POLICIES = {"fail_run", "warn", "disabled"}
_AUDIT_PAYLOAD_RETENTIONS = {"hash_only", "redacted", "full"}
_AUDIT_SINKS = {"postgres"}
_DUPLICATE_STRATEGIES = {"reject", "ignore"}
_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "access_token",
    "refresh_token",
    "secret",
    "token",
    "password",
}
_REDACTED = "[REDACTED]"


class AuditSinkFailure(RuntimeError):
    """Raised when audit capture must fail the run."""

    audit_failure_policy = "fail_run"


@dataclass(frozen=True)
class AuditPolicyConfig:
    """Normalized durable audit configuration."""

    enabled: bool = False
    sink: AuditSink = "postgres"
    dsn: str | None = None
    dsn_env: str | None = None
    failure_policy: AuditFailurePolicy = "warn"
    retention: str | None = None
    payload_retention: AuditPayloadRetention = "redacted"
    redaction_policy_id: str = "default"
    redacted_field_paths: tuple[str, ...] = ()
    duplicate_strategy: DuplicateStrategy = "reject"
    tags: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, config: Mapping[str, Any] | None) -> "AuditPolicyConfig":
        """Build audit policy from a root, observability, or audit-only mapping."""
        raw = _audit_mapping(config)
        if not raw:
            return cls()

        sink = _literal_value(raw, "sink", "postgres", _AUDIT_SINKS, "audit.sink")
        failure_policy = _literal_value(
            raw,
            "failure_policy",
            "warn",
            _AUDIT_FAILURE_POLICIES,
            "audit.failure_policy",
        )
        payload_retention = _literal_value(
            raw,
            "payload_retention",
            "redacted",
            _AUDIT_PAYLOAD_RETENTIONS,
            "audit.payload_retention",
        )
        duplicate_strategy = _literal_value(
            raw,
            "duplicate_strategy",
            "reject",
            _DUPLICATE_STRATEGIES,
            "audit.duplicate_strategy",
        )
        tags = raw.get("tags") or {}
        if not isinstance(tags, Mapping):
            raise ValueError("audit.tags must be a mapping of string keys to string values")

        dsn_env = raw.get("dsn_env")
        dsn = raw.get("dsn") or (os.getenv(str(dsn_env)) if dsn_env else None)
        enabled = bool(raw.get("enabled", False)) and failure_policy != "disabled"

        return cls(
            enabled=enabled,
            sink=sink,  # type: ignore[arg-type]
            dsn=str(dsn) if dsn else None,
            dsn_env=str(dsn_env) if dsn_env else None,
            failure_policy=failure_policy,  # type: ignore[arg-type]
            retention=str(raw["retention"]) if raw.get("retention") is not None else None,
            payload_retention=payload_retention,  # type: ignore[arg-type]
            redaction_policy_id=str(raw.get("redaction_policy_id", "default")),
            redacted_field_paths=tuple(str(path) for path in raw.get("redacted_field_paths") or ()),
            duplicate_strategy=duplicate_strategy,  # type: ignore[arg-type]
            tags={str(key): str(value) for key, value in tags.items()},
        )


def _audit_mapping(config: Mapping[str, Any] | None) -> Mapping[str, Any]:
    if not config:
        return {}
    if "observability" in config:
        return (config.get("observability") or {}).get("audit") or {}
    if "audit" in config:
        return config.get("audit") or {}
    return config


def _literal_value(
    raw: Mapping[str, Any],
    key: str,
    default: str,
    allowed: set[str],
    label: str,
) -> str:
    value = str(raw.get(key, default)).lower()
    if value not in allowed:
        allowed_values = ", ".join(sorted(allowed))
        raise ValueError(f"{label} must be one of: {allowed_values}")
    return value


def apply_audit_policy(event: BpgEvent, policy: AuditPolicyConfig) -> BpgEvent:
    """Return an event enriched with audit policy metadata."""
    payload = dict(event.payload or {})
    _, redacted_paths = redact_payload(payload, configured_paths=policy.redacted_field_paths)
    return event.model_copy(
        update={
            "redaction_policy_id": policy.redaction_policy_id,
            "redacted_field_paths": sorted(redacted_paths),
            "payload_sha256": event.payload_sha256 or sha256_json(payload),
            "tags": {**event.tags, **policy.tags},
        }
    )


def audit_payload_for_event(event: BpgEvent, policy: AuditPolicyConfig) -> dict[str, Any]:
    """Project an event payload according to the configured retention policy."""
    original_payload = dict(event.payload or {})
    original_payload_sha256 = sha256_json(original_payload)
    redacted_payload, redacted_paths = redact_payload(
        original_payload,
        configured_paths=policy.redacted_field_paths,
    )
    metadata: dict[str, Any] = {
        "payload_retention": policy.payload_retention,
        "payload_sha256": original_payload_sha256,
        "redaction_policy_id": policy.redaction_policy_id,
        "redacted_field_paths": sorted(redacted_paths),
        "tags": dict(policy.tags),
    }
    if policy.retention is not None:
        metadata["retention"] = policy.retention

    if policy.payload_retention == "hash_only":
        return {"_audit": metadata}
    if policy.payload_retention == "full":
        return {"_audit": metadata, "event_payload": original_payload}
    return {"_audit": metadata, "event_payload": redacted_payload}


def redact_payload(
    payload: Mapping[str, Any],
    *,
    configured_paths: Iterable[str] = (),
) -> tuple[dict[str, Any], set[str]]:
    """Redact configured dot paths and common sensitive keys from a payload."""
    redacted = _redact_sensitive_keys(payload, "$", set())
    paths: set[str] = set()
    redacted = _copy_json_like(redacted)
    for raw_path in configured_paths:
        path = _normalize_path(raw_path)
        if _redact_path(redacted, path):
            paths.add(_display_path(path))
    redacted, sensitive_paths = _collect_sensitive_paths(redacted, "$")
    paths.update(sensitive_paths)
    return redacted, paths


def _copy_json_like(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _copy_json_like(child) for key, child in value.items()}
    if isinstance(value, list):
        return [_copy_json_like(item) for item in value]
    return value


def _redact_sensitive_keys(value: Any, path: str, paths: set[str]) -> Any:
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, child in value.items():
            key_str = str(key)
            child_path = f"{path}.{key_str}"
            if key_str.lower() in _SENSITIVE_KEYS:
                out[key_str] = _REDACTED
                paths.add(child_path)
            else:
                out[key_str] = _redact_sensitive_keys(child, child_path, paths)
        return out
    if isinstance(value, list):
        return [_redact_sensitive_keys(item, f"{path}[{index}]", paths) for index, item in enumerate(value)]
    return value


def _collect_sensitive_paths(value: Any, path: str) -> tuple[Any, set[str]]:
    paths: set[str] = set()
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, child in value.items():
            key_str = str(key)
            child_path = f"{path}.{key_str}"
            if child == _REDACTED and key_str.lower() in _SENSITIVE_KEYS:
                paths.add(child_path)
            nested, nested_paths = _collect_sensitive_paths(child, child_path)
            out[key_str] = nested
            paths.update(nested_paths)
        return out, paths
    if isinstance(value, list):
        out_list = []
        for index, item in enumerate(value):
            nested, nested_paths = _collect_sensitive_paths(item, f"{path}[{index}]")
            out_list.append(nested)
            paths.update(nested_paths)
        return out_list, paths
    return value, paths


def _normalize_path(path: str) -> tuple[str, ...]:
    normalized = path.strip()
    if normalized.startswith("$."):
        normalized = normalized[2:]
    if normalized.startswith("payload."):
        normalized = normalized[len("payload.") :]
    return tuple(part for part in normalized.split(".") if part)


def _display_path(path: tuple[str, ...]) -> str:
    return "$." + ".".join(path)


def _redact_path(value: Any, path: tuple[str, ...]) -> bool:
    if not path:
        return False
    key = path[0]
    if isinstance(value, list):
        matched = False
        for item in value:
            matched = _redact_path(item, path) or matched
        return matched
    if not isinstance(value, dict) or key not in value:
        return False
    if len(path) == 1:
        value[key] = _REDACTED
        return True
    return _redact_path(value[key], path[1:])
