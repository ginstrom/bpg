"""HITL approval signal/query/state contract tests.

Tests approval gate state transitions, actor authorization,
timeout handling, and the query surface.
"""

from __future__ import annotations

import pytest

from bpg_temporal.hitl import (
    ActorIdentity,
    ApprovalGate,
    ApprovalOutcome,
    ApprovalRequest,
    ApprovalSignal,
    ApprovalState,
)


def _request(
    *,
    required_actor_ids: list[str] | None = None,
    timeout_seconds: float = 3600.0,
    escalation_timeout_seconds: float | None = None,
    escalation_actor_ids: list[str] | None = None,
) -> ApprovalRequest:
    return ApprovalRequest(
        request_id="req-001",
        workflow_id="wf-abc",
        node_id="send_invoice",
        correlation_id="corr-xyz",
        subject="Approve invoice #42",
        payload={"amount": 5000, "vendor": "Acme Corp"},
        required_actor_ids=required_actor_ids or [],
        timeout_seconds=timeout_seconds,
        escalation_timeout_seconds=escalation_timeout_seconds,
        escalation_actor_ids=escalation_actor_ids or [],
    )


def _actor(actor_id: str = "alice") -> ActorIdentity:
    return ActorIdentity(actor_id=actor_id, actor_type="human", display_name="Alice")


class TestApprovalGateInitialState:
    def test_starts_pending(self):
        gate = ApprovalGate(_request())
        assert gate.state.outcome == ApprovalOutcome.PENDING

    def test_not_resolved_initially(self):
        gate = ApprovalGate(_request())
        assert not gate.state.is_resolved

    def test_query_returns_request_id(self):
        gate = ApprovalGate(_request())
        result = gate.query_state()
        assert result["request_id"] == "req-001"

    def test_query_returns_pending_outcome(self):
        gate = ApprovalGate(_request())
        result = gate.query_state()
        assert result["outcome"] == "pending"

    def test_query_actor_id_is_none_initially(self):
        gate = ApprovalGate(_request())
        assert gate.query_state()["actor_id"] is None


class TestApprovalSignalTransitions:
    def test_approve_signal_transitions_to_approved(self):
        gate = ApprovalGate(_request())
        gate.send_signal(ApprovalSignal(
            outcome=ApprovalOutcome.APPROVED,
            actor=_actor(),
        ))
        assert gate.state.outcome == ApprovalOutcome.APPROVED

    def test_reject_signal_transitions_to_rejected(self):
        gate = ApprovalGate(_request())
        gate.send_signal(ApprovalSignal(
            outcome=ApprovalOutcome.REJECTED,
            actor=_actor(),
            reason="Budget exceeded",
        ))
        assert gate.state.outcome == ApprovalOutcome.REJECTED

    def test_escalate_signal_transitions_to_escalated(self):
        gate = ApprovalGate(_request())
        gate.send_signal(ApprovalSignal(
            outcome=ApprovalOutcome.ESCALATED,
            actor=_actor(),
            reason="Needs manager approval",
        ))
        assert gate.state.outcome == ApprovalOutcome.ESCALATED

    def test_resolved_after_approve(self):
        gate = ApprovalGate(_request())
        gate.send_signal(ApprovalSignal(outcome=ApprovalOutcome.APPROVED, actor=_actor()))
        assert gate.state.is_resolved

    def test_query_reflects_approval(self):
        gate = ApprovalGate(_request())
        gate.send_signal(ApprovalSignal(
            outcome=ApprovalOutcome.APPROVED,
            actor=_actor("bob"),
            reason="Looks good",
        ))
        result = gate.query_state()
        assert result["outcome"] == "approved"
        assert result["actor_id"] == "bob"
        assert result["reason"] == "Looks good"
        assert result["resolved_at"] is not None

    def test_cannot_signal_twice(self):
        gate = ApprovalGate(_request())
        gate.send_signal(ApprovalSignal(outcome=ApprovalOutcome.APPROVED, actor=_actor()))
        with pytest.raises(ValueError, match="already resolved"):
            gate.send_signal(ApprovalSignal(outcome=ApprovalOutcome.REJECTED, actor=_actor()))

    def test_pending_signal_outcome_rejected(self):
        gate = ApprovalGate(_request())
        with pytest.raises(ValueError, match="Invalid signal outcome"):
            gate.send_signal(ApprovalSignal(
                outcome=ApprovalOutcome.PENDING,
                actor=_actor(),
            ))


class TestApprovalTimeout:
    def test_timeout_transitions_to_timed_out(self):
        gate = ApprovalGate(_request())
        gate.apply_timeout()
        assert gate.state.outcome == ApprovalOutcome.TIMED_OUT

    def test_timeout_marks_resolved(self):
        gate = ApprovalGate(_request())
        gate.apply_timeout()
        assert gate.state.is_resolved

    def test_timeout_on_resolved_is_noop(self):
        gate = ApprovalGate(_request())
        gate.send_signal(ApprovalSignal(outcome=ApprovalOutcome.APPROVED, actor=_actor()))
        gate.apply_timeout()
        assert gate.state.outcome == ApprovalOutcome.APPROVED

    def test_timeout_query_shows_timed_out(self):
        gate = ApprovalGate(_request())
        gate.apply_timeout()
        assert gate.query_state()["outcome"] == "timed_out"


class TestActorAuthorization:
    def test_authorized_actor_can_approve(self):
        gate = ApprovalGate(_request(required_actor_ids=["alice", "bob"]))
        gate.send_signal(ApprovalSignal(outcome=ApprovalOutcome.APPROVED, actor=_actor("alice")))
        assert gate.state.outcome == ApprovalOutcome.APPROVED

    def test_unauthorized_actor_raises(self):
        gate = ApprovalGate(_request(required_actor_ids=["alice", "bob"]))
        with pytest.raises(PermissionError, match="not authorized"):
            gate.send_signal(ApprovalSignal(
                outcome=ApprovalOutcome.APPROVED,
                actor=_actor("charlie"),
            ))

    def test_open_approval_any_actor_allowed(self):
        gate = ApprovalGate(_request(required_actor_ids=[]))
        gate.send_signal(ApprovalSignal(outcome=ApprovalOutcome.APPROVED, actor=_actor("anyone")))
        assert gate.state.outcome == ApprovalOutcome.APPROVED


class TestApprovalRequestFields:
    def test_request_stores_all_fields(self):
        req = _request(
            timeout_seconds=7200.0,
            escalation_timeout_seconds=1800.0,
            escalation_actor_ids=["manager@example.com"],
        )
        assert req.timeout_seconds == 7200.0
        assert req.escalation_timeout_seconds == 1800.0
        assert req.escalation_actor_ids == ["manager@example.com"]

    def test_query_returns_workflow_and_node_ids(self):
        gate = ApprovalGate(_request())
        result = gate.query_state()
        assert result["workflow_id"] == "wf-abc"
        assert result["node_id"] == "send_invoice"

    def test_query_created_at_is_set(self):
        gate = ApprovalGate(_request())
        assert gate.query_state()["created_at"] is not None
