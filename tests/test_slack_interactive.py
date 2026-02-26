"""Tests for SlackInteractiveProvider and StateStore interaction methods.

Covers:
1. Unit tests for StateStore interaction methods (save/load pending and response).
2. Unit tests for SlackInteractiveProvider static helpers and poll/await_result.
3. Integration test: full LangGraph graph suspended at approval node, then resumed.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any, Dict

import pytest
from langgraph.checkpoint.memory import MemorySaver

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.models.schema import NodeStatus
from bpg.providers.base import ExecutionHandle, ExecutionStatus, ProviderError
from bpg.providers.mock import MockProvider
from bpg.providers.slack_interactive import SlackInteractiveProvider
from bpg.runtime.langgraph_runtime import LangGraphRuntime
from bpg.state.store import StateStore, StateStoreError

_PROCESS_FILE = Path("/home/ryan/play/bpg/process.bpg.yaml")

_FAKE_TS = "1234567890.000001"


def _fake_post_fn(
    token: str,
    channel: str,
    input_payload: Dict[str, Any],
    buttons: list,
    idempotency_key: str,
) -> str:
    """Fake Slack post function; returns a dummy message timestamp."""
    return _FAKE_TS


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def ir():
    """Compile the real process.bpg.yaml into an ExecutionIR once per module."""
    process = parse_process_file(_PROCESS_FILE)
    validate_process(process)
    return compile_process(process)


# ---------------------------------------------------------------------------
# 1. StateStore interaction method unit tests
# ---------------------------------------------------------------------------

class TestStateStoreInteractions:
    """Unit tests for save/load pending interaction and save/load response."""

    def test_save_and_load_pending_interaction(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        key = "abc123"
        data = {
            "run_id": "run-1",
            "node_name": "approval",
            "process_name": "bug-triage-process",
            "channel": "#ops",
            "message_ts": _FAKE_TS,
            "input": {"title": "High-risk bug"},
        }

        store.save_pending_interaction(key, data)
        record = store.load_pending_interaction(key)

        assert record is not None
        assert record["idempotency_key"] == key
        assert record["run_id"] == "run-1"
        assert record["node_name"] == "approval"
        assert record["channel"] == "#ops"
        assert record["message_ts"] == _FAKE_TS
        assert "created_at" in record

    def test_load_pending_interaction_missing(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        result = store.load_pending_interaction("does-not-exist")
        assert result is None

    def test_save_and_load_interaction_response(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        key = "def456"
        response = {"approved": True, "reason": "LGTM"}

        store.save_interaction_response(key, response)
        loaded = store.load_interaction_response(key)

        assert loaded is not None
        assert loaded["approved"] is True
        assert loaded["reason"] == "LGTM"

    def test_load_interaction_response_missing(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        result = store.load_interaction_response("no-such-key")
        assert result is None

    def test_pending_interaction_directory_created(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        key = "key-dir-test"
        store.save_pending_interaction(key, {"run_id": "r1", "node_name": "n1"})

        interaction_dir = tmp_path / "interactions" / key
        assert interaction_dir.is_dir()
        assert (interaction_dir / "pending.yaml").is_file()

    def test_response_directory_created_independently(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        key = "key-resp-only"
        # Save response without a pending record first
        store.save_interaction_response(key, {"approved": False, "reason": None})

        interaction_dir = tmp_path / "interactions" / key
        assert (interaction_dir / "response.yaml").is_file()

    def test_pending_and_response_coexist(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        key = "full-lifecycle"

        store.save_pending_interaction(key, {"run_id": "r1", "node_name": "approval"})
        store.save_interaction_response(key, {"approved": True, "reason": None})

        pending = store.load_pending_interaction(key)
        response = store.load_interaction_response(key)

        assert pending is not None
        assert response is not None
        assert response["approved"] is True


# ---------------------------------------------------------------------------
# 2. SlackInteractiveProvider unit tests (static helpers + poll/await_result)
# ---------------------------------------------------------------------------

class TestSlackInteractiveProviderHelpers:
    """Unit tests for parse_action, action_to_output, poll, and await_result."""

    def test_parse_action_valid_approve(self) -> None:
        key, label = SlackInteractiveProvider.parse_action("bpg__mykey123__approve")
        assert key == "mykey123"
        assert label == "approve"

    def test_parse_action_valid_reject(self) -> None:
        key, label = SlackInteractiveProvider.parse_action("bpg__abc__reject")
        assert key == "abc"
        assert label == "reject"

    def test_parse_action_invalid_prefix(self) -> None:
        with pytest.raises(ValueError, match="Not a BPG action_id"):
            SlackInteractiveProvider.parse_action("other__key__approve")

    def test_parse_action_too_few_parts(self) -> None:
        with pytest.raises(ValueError, match="Not a BPG action_id"):
            SlackInteractiveProvider.parse_action("bpg__onlytwoparts")

    def test_parse_action_too_many_parts(self) -> None:
        with pytest.raises(ValueError, match="Not a BPG action_id"):
            SlackInteractiveProvider.parse_action("bpg__key__approve__extra")

    def test_action_to_output_approve(self) -> None:
        result = SlackInteractiveProvider.action_to_output("approve")
        assert result["approved"] is True
        assert result["reason"] is None

    def test_action_to_output_yes(self) -> None:
        result = SlackInteractiveProvider.action_to_output("yes")
        assert result["approved"] is True

    def test_action_to_output_reject(self) -> None:
        result = SlackInteractiveProvider.action_to_output("reject")
        assert result["approved"] is False
        assert result["reason"] is None

    def test_action_to_output_no(self) -> None:
        result = SlackInteractiveProvider.action_to_output("no")
        assert result["approved"] is False

    def test_action_to_output_unknown_defaults_to_false(self) -> None:
        result = SlackInteractiveProvider.action_to_output("deny")
        assert result["approved"] is False

    def test_poll_returns_running_when_no_response(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        provider = SlackInteractiveProvider(store=store, bot_token="", post_fn=_fake_post_fn)

        handle = ExecutionHandle(
            handle_id="h1",
            idempotency_key="no-response-key",
            provider_id="slack.interactive",
            provider_data={},  # no "result" key
        )
        status = provider.poll(handle)
        assert status == ExecutionStatus.RUNNING

    def test_poll_returns_completed_when_result_in_handle(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        provider = SlackInteractiveProvider(store=store, bot_token="", post_fn=_fake_post_fn)

        handle = ExecutionHandle(
            handle_id="h2",
            idempotency_key="result-in-handle",
            provider_id="slack.interactive",
            provider_data={"result": {"approved": True}},
        )
        status = provider.poll(handle)
        assert status == ExecutionStatus.COMPLETED

    def test_poll_returns_completed_when_response_in_store(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        key = "stored-response-key"
        store.save_interaction_response(key, {"approved": True, "reason": None})

        provider = SlackInteractiveProvider(store=store, bot_token="", post_fn=_fake_post_fn)
        handle = ExecutionHandle(
            handle_id=key,
            idempotency_key=key,
            provider_id="slack.interactive",
            provider_data={},
        )
        status = provider.poll(handle)
        assert status == ExecutionStatus.COMPLETED

    def test_await_result_raises_when_no_response(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        provider = SlackInteractiveProvider(store=store, bot_token="", post_fn=_fake_post_fn)

        handle = ExecutionHandle(
            handle_id="no-resp",
            idempotency_key="no-resp",
            provider_id="slack.interactive",
            provider_data={},
        )
        with pytest.raises(ProviderError) as exc_info:
            provider.await_result(handle)
        assert exc_info.value.code == "no_response"

    def test_await_result_returns_result_from_handle(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        provider = SlackInteractiveProvider(store=store, bot_token="", post_fn=_fake_post_fn)

        handle = ExecutionHandle(
            handle_id="has-result",
            idempotency_key="has-result",
            provider_id="slack.interactive",
            provider_data={"result": {"approved": False, "reason": "nope"}},
        )
        result = provider.await_result(handle)
        assert result["approved"] is False
        assert result["reason"] == "nope"

    def test_await_result_falls_back_to_store(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        key = "fallback-key"
        store.save_interaction_response(key, {"approved": True, "reason": "from store"})

        provider = SlackInteractiveProvider(store=store, bot_token="", post_fn=_fake_post_fn)
        handle = ExecutionHandle(
            handle_id=key,
            idempotency_key=key,
            provider_id="slack.interactive",
            provider_data={},  # no "result"
        )
        result = provider.await_result(handle)
        assert result["approved"] is True

    def test_save_response_delegates_to_store(self, tmp_path: Path) -> None:
        store = StateStore(tmp_path)
        provider = SlackInteractiveProvider(store=store, bot_token="", post_fn=_fake_post_fn)
        key = "save-resp-key"

        provider.save_response(key, {"approved": True, "reason": "via provider"})
        loaded = store.load_interaction_response(key)

        assert loaded is not None
        assert loaded["approved"] is True


# ---------------------------------------------------------------------------
# 3. Integration test: full LangGraph graph with interrupt/resume
# ---------------------------------------------------------------------------

def _make_providers(
    slack_provider: SlackInteractiveProvider,
    mock: MockProvider,
) -> dict:
    """Build the provider registry mixing real SlackInteractiveProvider with mocks."""
    return {
        "dashboard.form": mock,
        "agent.pipeline": mock,
        "slack.interactive": slack_provider,
        "http.gitlab": mock,
    }


def test_integration_high_risk_interrupt_and_resume(ir, tmp_path: Path) -> None:
    """Full integration test: graph suspends at approval, then resumes with approval.

    Flow:
      1. runtime.run() with high-risk input — graph suspends at 'approval' node.
      2. Verify intake_form and triage are COMPLETED; approval not yet in statuses.
      3. provider.save_response(key, ...) — record the human response.
      4. runtime.resume(run_id, ...) — graph continues through approval → gitlab.
      5. Verify approval COMPLETED and gitlab COMPLETED.
    """
    store = StateStore(tmp_path)

    slack_provider = SlackInteractiveProvider(
        store=store,
        bot_token="",
        post_fn=_fake_post_fn,
    )

    mock = MockProvider()
    # triage returns high risk to trigger the approval branch
    mock.register_for_node("triage", {
        "risk": "high",
        "summary": "Critical data-exfiltration vector",
        "labels": ["security", "critical"],
        "recommended_assignee": "security-team",
    })
    # gitlab returns a ticket after approval
    mock.register_for_node("gitlab", {
        "ticket_id": "SEC-42",
        "url": "https://gitlab.example.com/issues/42",
    })

    checkpointer = MemorySaver()
    runtime = LangGraphRuntime(
        ir=ir,
        providers=_make_providers(slack_provider, mock),
        checkpointer=checkpointer,
    )

    run_id = str(uuid.uuid4())
    input_payload = {
        "title": "API leaks user tokens",
        "severity": "S1",
        "description": "The /export endpoint returns tokens in plaintext.",
        "reporter_email": "researcher@example.com",
    }

    # --- First invocation: graph should suspend at the approval node ---
    partial_state = runtime.run(input_payload=input_payload, run_id=run_id)

    # intake_form and triage should be COMPLETED
    assert partial_state["node_statuses"].get("intake_form") == NodeStatus.COMPLETED.value
    assert partial_state["node_statuses"].get("triage") == NodeStatus.COMPLETED.value

    # approval should not have a COMPLETED status yet (graph was suspended)
    assert partial_state["node_statuses"].get("approval") != NodeStatus.COMPLETED.value

    # Discover the idempotency key from the pending interactions directory
    interactions_dir = tmp_path / "interactions"
    assert interactions_dir.is_dir(), "Pending interactions directory was not created"
    pending_keys = list(interactions_dir.iterdir())
    assert len(pending_keys) == 1, f"Expected exactly one pending interaction, got {pending_keys}"
    idempotency_key = pending_keys[0].name

    # Verify the pending record contains expected metadata
    pending = store.load_pending_interaction(idempotency_key)
    assert pending is not None
    assert pending["node_name"] == "approval"
    assert pending["message_ts"] == _FAKE_TS

    # --- Simulate the Slack callback: record the human response ---
    human_response = {"approved": True, "reason": "LGTM"}
    slack_provider.save_response(idempotency_key, human_response)

    # Verify the response was persisted before resuming
    stored_response = store.load_interaction_response(idempotency_key)
    assert stored_response is not None
    assert stored_response["approved"] is True

    # --- Resume the graph with the human response ---
    final_state = runtime.resume(run_id=run_id, response=human_response)

    # approval should now be COMPLETED
    assert final_state["node_statuses"].get("approval") == NodeStatus.COMPLETED.value
    approval_output = final_state["node_outputs"].get("approval")
    assert approval_output is not None
    assert approval_output["approved"] is True

    # gitlab should be COMPLETED (approval.approved == true fired its edge)
    assert final_state["node_statuses"].get("gitlab") == NodeStatus.COMPLETED.value
    assert final_state["node_outputs"]["gitlab"]["ticket_id"] == "SEC-42"


def test_resume_raises_without_checkpointer(ir, tmp_path: Path) -> None:
    """resume() raises ValueError when no checkpointer was configured."""
    store = StateStore(tmp_path)
    slack_provider = SlackInteractiveProvider(
        store=store, bot_token="", post_fn=_fake_post_fn
    )
    mock = MockProvider()
    mock.set_default({})

    runtime = LangGraphRuntime(
        ir=ir,
        providers=_make_providers(slack_provider, mock),
        checkpointer=None,
    )

    with pytest.raises(ValueError, match="checkpointer"):
        runtime.resume(run_id="any-id", response={"approved": True})
