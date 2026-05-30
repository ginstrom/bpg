"""HITL approval signal/query/state contract for Temporal-owned wait states."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ApprovalOutcome(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ESCALATED = "escalated"
    TIMED_OUT = "timed_out"


@dataclass(frozen=True)
class ActorIdentity:
    actor_id: str
    actor_type: str = "human"
    display_name: str | None = None


@dataclass(frozen=True)
class ApprovalRequest:
    request_id: str
    workflow_id: str
    node_id: str
    correlation_id: str
    subject: str
    payload: dict[str, Any]
    required_actor_ids: list[str] = field(default_factory=list)
    timeout_seconds: float = 86400.0
    escalation_timeout_seconds: float | None = None
    escalation_actor_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ApprovalSignal:
    outcome: ApprovalOutcome
    actor: ActorIdentity
    reason: str | None = None
    timestamp: str = field(default_factory=_utc_now)


@dataclass
class ApprovalState:
    request: ApprovalRequest
    outcome: ApprovalOutcome = ApprovalOutcome.PENDING
    signal: ApprovalSignal | None = None
    created_at: str = field(default_factory=_utc_now)

    @property
    def is_resolved(self) -> bool:
        return self.outcome != ApprovalOutcome.PENDING

    def apply_signal(self, signal: ApprovalSignal) -> None:
        if self.outcome != ApprovalOutcome.PENDING:
            raise ValueError(f"Approval already resolved: {self.outcome.value}")
        if signal.outcome not in (
            ApprovalOutcome.APPROVED,
            ApprovalOutcome.REJECTED,
            ApprovalOutcome.ESCALATED,
        ):
            raise ValueError(f"Invalid signal outcome: {signal.outcome.value}")
        required = self.request.required_actor_ids
        if required and signal.actor.actor_id not in required:
            raise PermissionError(
                f"Actor {signal.actor.actor_id!r} is not authorized to resolve this approval"
            )
        self.outcome = signal.outcome
        self.signal = signal

    def apply_timeout(self) -> None:
        if self.outcome != ApprovalOutcome.PENDING:
            return
        self.outcome = ApprovalOutcome.TIMED_OUT


class ApprovalGate:
    """Framework wait-state manager for Temporal-owned approval flows.

    Encapsulates the signal contract (approve/reject/escalate), query surface,
    and timeout handling without depending on a live Temporal worker.
    """

    def __init__(self, request: ApprovalRequest) -> None:
        self._state = ApprovalState(request=request)

    @property
    def state(self) -> ApprovalState:
        return self._state

    def send_signal(self, signal: ApprovalSignal) -> None:
        """Apply an approval signal to transition state."""
        self._state.apply_signal(signal)

    def apply_timeout(self) -> None:
        """Trigger timeout transition — maps to a Temporal timer firing."""
        self._state.apply_timeout()

    def query_state(self) -> dict[str, Any]:
        """Return a serializable snapshot — maps to a Temporal query handler."""
        s = self._state
        return {
            "request_id": s.request.request_id,
            "workflow_id": s.request.workflow_id,
            "node_id": s.request.node_id,
            "outcome": s.outcome.value,
            "actor_id": s.signal.actor.actor_id if s.signal else None,
            "reason": s.signal.reason if s.signal else None,
            "created_at": s.created_at,
            "resolved_at": s.signal.timestamp if s.signal else None,
        }
