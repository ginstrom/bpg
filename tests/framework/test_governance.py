"""Governance policy enforcement and approval-gated flow tests."""

from __future__ import annotations

import pytest

from bpg_temporal.governance import (
    ApprovalRequiredPolicy,
    EscalationPolicy,
    GovernancePolicy,
    PolicyContext,
    PolicyEngine,
    PolicyViolation,
)
from bpg_temporal.hitl import (
    ActorIdentity,
    ApprovalGate,
    ApprovalOutcome,
    ApprovalRequest,
    ApprovalSignal,
)


def _ctx(
    node_id: str = "deploy",
    actor_id: str | None = None,
    **attrs: object,
) -> PolicyContext:
    return PolicyContext(
        workflow_id="wf-gov-test",
        node_id=node_id,
        actor_id=actor_id,
        payload={"action": node_id},
        attributes=dict(attrs),
    )


class TestPolicyViolation:
    def test_carries_policy_id(self):
        exc = PolicyViolation(policy_id="pol-1", reason="blocked")
        assert exc.policy_id == "pol-1"

    def test_carries_reason(self):
        exc = PolicyViolation(policy_id="pol-1", reason="needs approval")
        assert exc.reason == "needs approval"

    def test_is_exception(self):
        exc = PolicyViolation(policy_id="p", reason="r")
        assert isinstance(exc, Exception)

    def test_str_contains_policy_id(self):
        exc = PolicyViolation(policy_id="my-policy", reason="blocked")
        assert "my-policy" in str(exc)


class TestApprovalRequiredPolicy:
    def test_blocks_unapproved_node(self):
        policy = ApprovalRequiredPolicy(
            policy_id="require-approval",
            required_for_nodes=["deploy", "delete_data"],
        )
        with pytest.raises(PolicyViolation) as exc_info:
            policy.check(_ctx("deploy"))
        assert exc_info.value.policy_id == "require-approval"

    def test_allows_approved_node(self):
        policy = ApprovalRequiredPolicy(
            policy_id="require-approval",
            required_for_nodes=["deploy"],
        )
        policy.check(_ctx("deploy", approval_granted=True))

    def test_allows_unrestricted_node(self):
        policy = ApprovalRequiredPolicy(
            policy_id="require-approval",
            required_for_nodes=["deploy"],
        )
        policy.check(_ctx("fetch_data"))

    def test_is_governance_policy(self):
        policy = ApprovalRequiredPolicy(policy_id="p", required_for_nodes=[])
        assert isinstance(policy, GovernancePolicy)


class TestEscalationPolicy:
    def test_stores_timeout(self):
        policy = EscalationPolicy(
            policy_id="escalate-24h",
            timeout_seconds=86400.0,
            escalation_actor_ids=["manager@example.com"],
        )
        assert policy.timeout_seconds == 86400.0

    def test_stores_escalation_targets(self):
        policy = EscalationPolicy(
            policy_id="escalate",
            timeout_seconds=3600.0,
            escalation_actor_ids=["a@b.com", "c@d.com"],
        )
        assert policy.escalation_targets() == ["a@b.com", "c@d.com"]

    def test_check_does_not_block_by_default(self):
        policy = EscalationPolicy(
            policy_id="escalate",
            timeout_seconds=3600.0,
            escalation_actor_ids=[],
        )
        policy.check(_ctx())

    def test_is_governance_policy(self):
        policy = EscalationPolicy(policy_id="p", timeout_seconds=60.0, escalation_actor_ids=[])
        assert isinstance(policy, GovernancePolicy)


class TestPolicyEngine:
    def test_enforce_with_no_policies_passes(self):
        engine = PolicyEngine()
        engine.enforce(_ctx())

    def test_is_allowed_no_policies(self):
        engine = PolicyEngine()
        assert engine.is_allowed(_ctx())

    def test_enforce_passes_all_policies_satisfied(self):
        engine = PolicyEngine(policies=[
            ApprovalRequiredPolicy(policy_id="p1", required_for_nodes=["deploy"]),
        ])
        engine.enforce(_ctx("deploy", approval_granted=True))

    def test_enforce_raises_on_first_violation(self):
        engine = PolicyEngine(policies=[
            ApprovalRequiredPolicy(policy_id="pol-1", required_for_nodes=["deploy"]),
        ])
        with pytest.raises(PolicyViolation) as exc_info:
            engine.enforce(_ctx("deploy"))
        assert exc_info.value.policy_id == "pol-1"

    def test_is_allowed_returns_false_on_violation(self):
        engine = PolicyEngine(policies=[
            ApprovalRequiredPolicy(policy_id="pol-1", required_for_nodes=["delete"]),
        ])
        assert not engine.is_allowed(_ctx("delete"))

    def test_add_policy_dynamically(self):
        engine = PolicyEngine()
        engine.add_policy(ApprovalRequiredPolicy(policy_id="p2", required_for_nodes=["deploy"]))
        with pytest.raises(PolicyViolation):
            engine.enforce(_ctx("deploy"))

    def test_multiple_policies_all_checked(self):
        engine = PolicyEngine(policies=[
            ApprovalRequiredPolicy(policy_id="pol-a", required_for_nodes=["action-a"]),
            ApprovalRequiredPolicy(policy_id="pol-b", required_for_nodes=["action-b"]),
        ])
        engine.enforce(_ctx("other"))
        with pytest.raises(PolicyViolation) as exc_info:
            engine.enforce(_ctx("action-a"))
        assert exc_info.value.policy_id == "pol-a"


class TestApprovalGatedFlow:
    """End-to-end: gate blocks execution, approval unblocks it."""

    def test_gate_blocks_until_approved(self):
        req = ApprovalRequest(
            request_id="req-flow-1",
            workflow_id="wf-flow",
            node_id="deploy",
            correlation_id="corr-flow",
            subject="Deploy to production",
            payload={},
        )
        gate = ApprovalGate(req)
        policy = ApprovalRequiredPolicy(
            policy_id="require-deploy-approval",
            required_for_nodes=["deploy"],
        )
        engine = PolicyEngine(policies=[policy])

        ctx_before = PolicyContext(
            workflow_id="wf-flow",
            node_id="deploy",
            actor_id=None,
            payload={},
            attributes={"approval_granted": gate.state.outcome == ApprovalOutcome.APPROVED},
        )
        assert not engine.is_allowed(ctx_before)

        gate.send_signal(ApprovalSignal(
            outcome=ApprovalOutcome.APPROVED,
            actor=ActorIdentity(actor_id="ops-lead", actor_type="human"),
        ))

        ctx_after = PolicyContext(
            workflow_id="wf-flow",
            node_id="deploy",
            actor_id="ops-lead",
            payload={},
            attributes={"approval_granted": gate.state.outcome == ApprovalOutcome.APPROVED},
        )
        assert engine.is_allowed(ctx_after)

    def test_timeout_leaves_gate_unresolved_for_policy(self):
        req = ApprovalRequest(
            request_id="req-flow-2",
            workflow_id="wf-flow",
            node_id="send_invoice",
            correlation_id="corr-flow-2",
            subject="Send invoice",
            payload={},
        )
        gate = ApprovalGate(req)
        gate.apply_timeout()

        policy = ApprovalRequiredPolicy(
            policy_id="require-invoice-approval",
            required_for_nodes=["send_invoice"],
        )
        engine = PolicyEngine(policies=[policy])

        ctx = PolicyContext(
            workflow_id="wf-flow",
            node_id="send_invoice",
            actor_id=None,
            payload={},
            attributes={"approval_granted": gate.state.outcome == ApprovalOutcome.APPROVED},
        )
        assert not engine.is_allowed(ctx)
