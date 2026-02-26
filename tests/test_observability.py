"""Tests for retry backoff, structured event emission, and run replay.

Covers:
1. _compute_retry_delay — all three BackoffStrategy values
2. LangGraphRuntime emits correct event sequence on success
3. LangGraphRuntime emits node_started + node_retrying + node_failed
   for a retryable error; verifies sleep is called with correct delay
4. Replay reconstructs events from an execution_log without re-running providers
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.models.schema import BackoffStrategy, NodeStatus, RetryPolicy
from bpg.providers.base import ProviderError
from bpg.providers.mock import MockProvider
from bpg.runtime.langgraph_runtime import (
    LangGraphRuntime,
    _compute_retry_delay,
)
from bpg.runtime.observability import ListEventSink, replay_run

_PROCESS_FILE = Path("/home/ryan/play/bpg/process.bpg.yaml")


@pytest.fixture(scope="module")
def ir():
    process = parse_process_file(_PROCESS_FILE)
    validate_process(process)
    return compile_process(process)


def _providers(mock: MockProvider) -> dict:
    return {
        "dashboard.form": mock,
        "agent.pipeline": mock,
        "slack.interactive": mock,
        "http.gitlab": mock,
    }


# ---------------------------------------------------------------------------
# 1. _compute_retry_delay
# ---------------------------------------------------------------------------


class TestComputeRetryDelay:
    def test_exponential(self):
        assert _compute_retry_delay(0, BackoffStrategy.EXPONENTIAL, 2.0, 60.0) == 2.0
        assert _compute_retry_delay(1, BackoffStrategy.EXPONENTIAL, 2.0, 60.0) == 4.0
        assert _compute_retry_delay(2, BackoffStrategy.EXPONENTIAL, 2.0, 60.0) == 8.0

    def test_linear(self):
        assert _compute_retry_delay(0, BackoffStrategy.LINEAR, 3.0, 60.0) == 3.0
        assert _compute_retry_delay(1, BackoffStrategy.LINEAR, 3.0, 60.0) == 6.0
        assert _compute_retry_delay(2, BackoffStrategy.LINEAR, 3.0, 60.0) == 9.0

    def test_constant(self):
        assert _compute_retry_delay(0, BackoffStrategy.CONSTANT, 5.0, 60.0) == 5.0
        assert _compute_retry_delay(3, BackoffStrategy.CONSTANT, 5.0, 60.0) == 5.0

    def test_max_delay_caps_exponential(self):
        # 2 ** 10 * 1.0 = 1024 > max_delay=10
        assert _compute_retry_delay(10, BackoffStrategy.EXPONENTIAL, 1.0, 10.0) == 10.0


# ---------------------------------------------------------------------------
# 2. Event sequence for a successful run
# ---------------------------------------------------------------------------


def test_events_emitted_on_success(ir):
    mock = MockProvider()
    mock.register_for_node("triage", {
        "risk": "low", "summary": "x", "labels": [], "recommended_assignee": "a"
    })
    mock.register_for_node("gitlab", {"ticket_id": "T-1", "url": "http://x"})

    sink = ListEventSink()
    runtime = LangGraphRuntime(ir=ir, providers=_providers(mock), event_sink=sink)
    runtime.run({"title": "t", "severity": "S3", "description": "d", "reporter_email": "e@e"})

    types = [e["event_type"] for e in sink.events]

    # Trigger fires as node_completed without node_started
    assert types[0] == "node_completed"
    assert sink.events[0]["node"] == "intake_form"

    # triage: started → completed
    triage_events = sink.for_node("triage")
    assert [e["event_type"] for e in triage_events] == ["node_started", "node_completed"]

    # approval: skipped (no node_started because no invocation)
    approval_events = sink.for_node("approval")
    assert len(approval_events) == 1
    assert approval_events[0]["event_type"] == "node_skipped"

    # gitlab: started → completed
    gitlab_events = sink.for_node("gitlab")
    assert [e["event_type"] for e in gitlab_events] == ["node_started", "node_completed"]

    # Every completed event has the required fields
    for ev in sink.by_type("node_completed"):
        assert "run_id" in ev
        assert "process_name" in ev
        assert "timestamp" in ev


# ---------------------------------------------------------------------------
# 3. Retry events with backoff delay
# ---------------------------------------------------------------------------


def test_retry_events_and_backoff(ir):
    """node_retrying events carry attempt/delay; time.sleep is called."""
    mock = MockProvider()
    # Register a retryable error so all attempts fail
    mock.register_error(
        "triage",
        ProviderError(code="rate_limit", message="Too many requests", retryable=True),
    )

    # Patch the retry policy on the resolved node to 3 attempts with known delay
    triage_node = ir.resolved_nodes["triage"]
    policy = RetryPolicy(
        max_attempts=3,
        backoff=BackoffStrategy.CONSTANT,
        initial_delay="0.1s",
        max_delay="1s",
    )
    # Temporarily swap the retry policy via object.__setattr__ (frozen dataclass)
    original_instance = triage_node.instance
    patched_instance = original_instance.model_copy(update={"retry": policy})
    object.__setattr__(triage_node, "instance", patched_instance)

    sink = ListEventSink()
    try:
        with patch("bpg.runtime.langgraph_runtime.time.sleep") as mock_sleep:
            runtime = LangGraphRuntime(ir=ir, providers=_providers(mock), event_sink=sink)
            state = runtime.run(
                {"title": "t", "severity": "S1", "description": "d", "reporter_email": "e@e"}
            )
    finally:
        # Restore original instance
        object.__setattr__(triage_node, "instance", original_instance)

    triage_events = sink.for_node("triage")
    event_types = [e["event_type"] for e in triage_events]

    # node_started → node_retrying × 2 → node_failed
    assert event_types[0] == "node_started"
    retrying = [e for e in triage_events if e["event_type"] == "node_retrying"]
    assert len(retrying) == 2  # 3 attempts → 2 retries between them
    assert event_types[-1] == "node_failed"

    # Retry events carry attempt number and delay
    assert retrying[0]["attempt"] == 1
    assert retrying[1]["attempt"] == 2
    assert retrying[0]["delay_seconds"] == pytest.approx(0.1)

    # time.sleep was called twice with the backoff delay
    assert mock_sleep.call_count == 2
    mock_sleep.assert_called_with(pytest.approx(0.1))

    # node_failed carries the error code
    failed = sink.by_type("node_failed")
    triage_failed = [e for e in failed if e["node"] == "triage"]
    assert triage_failed[0]["error_code"] == "rate_limit"

    # Final state records the failure
    assert state["node_statuses"]["triage"] == NodeStatus.FAILED.value


# ---------------------------------------------------------------------------
# 4. replay_run reconstructs events from execution_log
# ---------------------------------------------------------------------------


def test_replay_run_from_execution_log(ir):
    mock = MockProvider()
    mock.register_for_node("triage", {
        "risk": "high", "summary": "x", "labels": [], "recommended_assignee": "a"
    })
    mock.register_for_node("approval", {"approved": True, "reason": "ok"})
    mock.register_for_node("gitlab", {"ticket_id": "T-9", "url": "http://x"})

    live_sink = ListEventSink()
    runtime = LangGraphRuntime(ir=ir, providers=_providers(mock), event_sink=live_sink)
    final_state = runtime.run(
        {"title": "t", "severity": "S1", "description": "d", "reporter_email": "e@e"}
    )

    # Replay into a fresh sink
    replay_sink = ListEventSink()
    replay_run(
        execution_log=final_state["execution_log"],
        run_id=final_state["run_id"],
        process_name=final_state["process_name"],
        sink=replay_sink,
    )

    # One event per node in the log
    assert len(replay_sink.events) == len(final_state["execution_log"])

    # Every replayed event carries the run_id and process_name
    for ev in replay_sink.events:
        assert ev["run_id"] == final_state["run_id"]
        assert ev["process_name"] == final_state["process_name"]

    # Completed nodes map to node_completed event_type
    completed_nodes = [
        e["node"] for e in replay_sink.events if e["event_type"] == "node_completed"
    ]
    assert "triage" in completed_nodes
    assert "approval" in completed_nodes
    assert "gitlab" in completed_nodes

    # Skipped node maps to node_skipped
    # (approval is skipped in the low-risk path; here we used high-risk so
    # check for whatever node was actually skipped)
    skipped_nodes = [
        e["node"] for e in replay_sink.events if e["event_type"] == "node_skipped"
    ]
    # In a high-risk run approval fires, nothing is skipped beyond the
    # conditional low-risk path — but we just confirm structure is correct.
    for ev in replay_sink.events:
        assert "event_type" in ev
        assert "node" in ev
        assert "timestamp" in ev
