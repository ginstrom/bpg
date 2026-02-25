"""Tests for LangGraphRuntime end-to-end process execution.

All tests use the real process.bpg.yaml and MockProvider to exercise the full
LangGraph execution path without external dependencies.

Test scenarios:
1. Linear flow (no conditions): trigger passes through, low-risk bug goes
   directly to gitlab (skipping approval).
2. Conditional branching: high-risk bug triggers approval before gitlab.
3. Failed node: MockProvider raises ProviderError; node recorded as failed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.models.schema import NodeStatus
from bpg.providers.base import ProviderError
from bpg.providers.mock import MockProvider
from bpg.runtime.langgraph_runtime import LangGraphRuntime

_PROCESS_FILE = Path("/home/ryan/play/bpg/process.bpg.yaml")


@pytest.fixture(scope="module")
def ir():
    """Compile the real process.bpg.yaml into an ExecutionIR once per module."""
    process = parse_process_file(_PROCESS_FILE)
    validate_process(process)
    return compile_process(process)


def _make_providers(*mocks: MockProvider) -> dict:
    """Return a providers dict mapping every provider_id used in the process
    to the given MockProvider instance(s).  For simplicity in tests a single
    mock handles all providers."""
    mock = mocks[0] if mocks else MockProvider()
    return {
        "dashboard.form": mock,
        "agent.pipeline": mock,
        "slack.interactive": mock,
        "http.gitlab": mock,
    }


# ---------------------------------------------------------------------------
# Test 1: Linear / low-risk flow
#   intake_form → triage (risk=low) → gitlab (approval skipped)
# ---------------------------------------------------------------------------


def test_linear_flow_low_risk(ir):
    """Low-risk bug: intake_form → triage → gitlab; approval node is skipped."""
    mock = MockProvider()

    # triage returns low risk
    mock.register_for_node("triage", {
        "risk": "low",
        "summary": "Minor UI glitch on login page",
        "labels": ["ui", "low-priority"],
        "recommended_assignee": "alice",
    })
    # gitlab returns ticket info
    mock.register_for_node("gitlab", {
        "ticket_id": "PROJ-42",
        "url": "https://gitlab.example.com/issues/42",
    })

    runtime = LangGraphRuntime(ir=ir, providers=_make_providers(mock))

    input_payload = {
        "title": "Login button misaligned",
        "severity": "S3",
        "description": "The login button appears 2px off-center on Firefox.",
        "reporter_email": "user@example.com",
    }
    final_state = runtime.run(input_payload=input_payload)

    # Trigger (intake_form) completed
    assert final_state["node_statuses"]["intake_form"] == NodeStatus.COMPLETED.value

    # Triage completed
    assert final_state["node_statuses"]["triage"] == NodeStatus.COMPLETED.value
    assert final_state["node_outputs"]["triage"]["risk"] == "low"

    # Approval skipped (risk != "high")
    assert final_state["node_statuses"]["approval"] == NodeStatus.SKIPPED.value
    assert "approval" not in final_state["node_outputs"]

    # Gitlab completed (came from triage directly)
    assert final_state["node_statuses"]["gitlab"] == NodeStatus.COMPLETED.value
    assert final_state["node_outputs"]["gitlab"]["ticket_id"] == "PROJ-42"

    # Execution log has entries for all four nodes
    node_names_in_log = [entry["node"] for entry in final_state["execution_log"]]
    assert "intake_form" in node_names_in_log
    assert "triage" in node_names_in_log
    assert "approval" in node_names_in_log
    assert "gitlab" in node_names_in_log


# ---------------------------------------------------------------------------
# Test 2: Conditional branching — high-risk flow
#   intake_form → triage (risk=high) → approval → gitlab
# ---------------------------------------------------------------------------


def test_conditional_branch_high_risk(ir):
    """High-risk bug: triage fires approval edge, approval fires gitlab edge."""
    mock = MockProvider()

    # triage returns high risk
    mock.register_for_node("triage", {
        "risk": "high",
        "summary": "Data exfiltration vector in API",
        "labels": ["security", "critical"],
        "recommended_assignee": "security-team",
    })
    # approval returns approved
    mock.register_for_node("approval", {
        "approved": True,
        "reason": "Confirmed critical — escalating immediately.",
    })
    # gitlab returns ticket info
    mock.register_for_node("gitlab", {
        "ticket_id": "PROJ-99",
        "url": "https://gitlab.example.com/issues/99",
    })

    runtime = LangGraphRuntime(ir=ir, providers=_make_providers(mock))

    input_payload = {
        "title": "API leaks user tokens",
        "severity": "S1",
        "description": "The /export endpoint returns tokens in plaintext.",
        "reporter_email": "researcher@example.com",
    }
    final_state = runtime.run(input_payload=input_payload)

    # intake_form and triage completed
    assert final_state["node_statuses"]["intake_form"] == NodeStatus.COMPLETED.value
    assert final_state["node_statuses"]["triage"] == NodeStatus.COMPLETED.value

    # Approval completed (risk == "high" fired the edge)
    assert final_state["node_statuses"]["approval"] == NodeStatus.COMPLETED.value
    assert final_state["node_outputs"]["approval"]["approved"] is True

    # Gitlab completed (approval.approved == true fired its edge)
    assert final_state["node_statuses"]["gitlab"] == NodeStatus.COMPLETED.value
    assert final_state["node_outputs"]["gitlab"]["ticket_id"] == "PROJ-99"

    # Verify triage → approval edge was exercised (approval was invoked)
    approval_calls = [c for c in mock.calls if c.node_name == "approval"]
    assert len(approval_calls) == 1
    # Approval input should include the interpolated title from the mapping
    assert "High-risk bug:" in approval_calls[0].input.get("title", "")


# ---------------------------------------------------------------------------
# Test 3: Failed node — ProviderError propagated
# ---------------------------------------------------------------------------


def test_failed_node_provider_error(ir):
    """When a provider raises ProviderError the node is recorded as failed."""
    mock = MockProvider()

    # triage will fail
    mock.register_error(
        "triage",
        ProviderError(code="rate_limit", message="Too many requests", retryable=True),
    )

    runtime = LangGraphRuntime(ir=ir, providers=_make_providers(mock))

    input_payload = {
        "title": "Crash on startup",
        "severity": "S1",
        "description": "Application crashes immediately after launch.",
        "reporter_email": "dev@example.com",
    }
    final_state = runtime.run(input_payload=input_payload)

    # intake_form completed as trigger
    assert final_state["node_statuses"]["intake_form"] == NodeStatus.COMPLETED.value

    # triage failed
    assert final_state["node_statuses"]["triage"] == NodeStatus.FAILED.value

    # approval and gitlab should be skipped (triage did not complete)
    assert final_state["node_statuses"].get("approval") == NodeStatus.SKIPPED.value
    assert final_state["node_statuses"].get("gitlab") == NodeStatus.SKIPPED.value

    # Execution log should include error entry for triage
    triage_log = [e for e in final_state["execution_log"] if e["node"] == "triage"]
    assert len(triage_log) == 1
    assert triage_log[0]["status"] == NodeStatus.FAILED.value
    assert "rate_limit" in triage_log[0].get("error", "")
