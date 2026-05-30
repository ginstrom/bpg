"""Audit event schema for BPG framework governance and observability."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class AuditEventType(str, Enum):
    APPROVAL_REQUESTED = "approval_requested"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    TIMED_OUT = "timed_out"
    POLICY_CHECKED = "policy_checked"
    POLICY_BLOCKED = "policy_blocked"
    NODE_STARTED = "node_started"
    NODE_COMPLETED = "node_completed"
    NODE_FAILED = "node_failed"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuditEvent(BaseModel):
    """Canonical audit record emitted by framework governance and HITL operations."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: AuditEventType
    workflow_id: str
    node_id: str
    timestamp: str = Field(default_factory=_utc_now)
    actor_id: str | None = None
    policy_id: str | None = None
    correlation_id: str | None = None
    external_ref: str | None = None
    reason: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class AuditSink(ABC):
    """Abstract sink for audit events."""

    @abstractmethod
    def emit(self, event: AuditEvent) -> None:
        """Record an audit event. Must not raise."""


class ListAuditSink(AuditSink):
    """In-memory audit sink for testing and debugging."""

    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def emit(self, event: AuditEvent) -> None:
        self.events.append(event)

    def by_type(self, event_type: AuditEventType) -> list[AuditEvent]:
        return [e for e in self.events if e.event_type == event_type]

    def for_node(self, node_id: str) -> list[AuditEvent]:
        return [e for e in self.events if e.node_id == node_id]
