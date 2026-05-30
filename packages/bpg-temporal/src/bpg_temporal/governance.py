"""Governance hooks for policy enforcement in Temporal-owned workflows."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class PolicyViolation(Exception):
    """Raised when a governance policy blocks execution."""

    def __init__(self, policy_id: str, reason: str) -> None:
        super().__init__(f"Policy {policy_id!r} blocked execution: {reason}")
        self.policy_id = policy_id
        self.reason = reason


@dataclass(frozen=True)
class PolicyContext:
    workflow_id: str
    node_id: str
    actor_id: str | None
    payload: dict[str, Any]
    attributes: dict[str, Any] = field(default_factory=dict)


class GovernancePolicy:
    """Abstract base for framework governance policies."""

    policy_id: str

    def check(self, context: PolicyContext) -> None:
        """Raise PolicyViolation if this policy blocks the action."""
        raise NotImplementedError


class ApprovalRequiredPolicy(GovernancePolicy):
    """Blocks execution of named nodes until approval_granted is set in context attributes."""

    def __init__(self, policy_id: str, required_for_nodes: list[str]) -> None:
        self.policy_id = policy_id
        self.required_for_nodes = set(required_for_nodes)

    def check(self, context: PolicyContext) -> None:
        if context.node_id in self.required_for_nodes:
            if not context.attributes.get("approval_granted"):
                raise PolicyViolation(
                    self.policy_id,
                    f"Node {context.node_id!r} requires approval before execution",
                )


class EscalationPolicy(GovernancePolicy):
    """Defines escalation targets and timeout for approval flows.

    Does not block execution inline — escalation is triggered by timeout
    in the Temporal workflow timer.
    """

    def __init__(
        self,
        policy_id: str,
        timeout_seconds: float,
        escalation_actor_ids: list[str],
    ) -> None:
        self.policy_id = policy_id
        self.timeout_seconds = timeout_seconds
        self.escalation_actor_ids = list(escalation_actor_ids)

    def escalation_targets(self) -> list[str]:
        return self.escalation_actor_ids

    def check(self, context: PolicyContext) -> None:
        pass


class PolicyEngine:
    """Evaluates an ordered list of governance policies against a context."""

    def __init__(self, policies: list[GovernancePolicy] | None = None) -> None:
        self._policies: list[GovernancePolicy] = list(policies or [])

    def add_policy(self, policy: GovernancePolicy) -> None:
        self._policies.append(policy)

    def enforce(self, context: PolicyContext) -> None:
        """Run all policies in order; raises PolicyViolation on first failure."""
        for policy in self._policies:
            policy.check(context)

    def is_allowed(self, context: PolicyContext) -> bool:
        """Return True if all policies pass, False if any raises PolicyViolation."""
        try:
            self.enforce(context)
            return True
        except PolicyViolation:
            return False
