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
import threading
import time

import pytest
import yaml

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.models.schema import NodeStatus
from bpg.providers.base import ProviderError
from bpg.providers.mock import MockProvider
from bpg.runtime.langgraph_runtime import LangGraphRuntime
from bpg.runtime.observability import ListEventSink

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


def test_failed_node_provider_error(ir, monkeypatch):
    """When a provider raises ProviderError the node is recorded as failed."""
    mock = MockProvider()
    slept: list[float] = []

    # Exercise retry/backoff logic without wall-clock waiting.
    monkeypatch.setattr(
        "bpg.runtime.langgraph_runtime.time.sleep",
        lambda seconds: slept.append(float(seconds)),
    )

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
    triage_calls = [c for c in mock.calls if c.node_name == "triage"]
    assert len(triage_calls) == 3
    assert slept == [5.0, 10.0]
    assert final_state["run_status"] == NodeStatus.FAILED.value


# ---------------------------------------------------------------------------
# Test 4: Only declared trigger is pass-through
# ---------------------------------------------------------------------------


def test_only_declared_trigger_is_trigger_behavior(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
types:
  In:
    title: string
  Out:
    ok: bool
node_types:
  trigger_node@v1:
    in: In
    out: In
    provider: mock
    version: v1
    config_schema: {}
  worker_node@v1:
    in: In
    out: Out
    provider: mock
    version: v1
    config_schema: {}
nodes:
  start:
    type: trigger_node@v1
    config: {}
  orphan:
    type: worker_node@v1
    config: {}
  work:
    type: worker_node@v1
    config: {}
trigger: start
edges:
  - from: start
    to: work
    with:
      title: trigger.in.title
"""
    )
    process = parse_process_file(process_file)
    validate_process(process)
    ir = compile_process(process)

    mock = MockProvider()
    mock.register_for_node("work", {"ok": True})

    runtime = LangGraphRuntime(
        ir=ir,
        providers={"mock": mock},
    )
    final_state = runtime.run(input_payload={"title": "x"})

    assert final_state["node_statuses"]["start"] == NodeStatus.COMPLETED.value
    assert final_state["node_statuses"]["orphan"] == NodeStatus.SKIPPED.value
    assert final_state["node_statuses"]["work"] == NodeStatus.COMPLETED.value
    orphan_calls = [c for c in mock.calls if c.node_name == "orphan"]
    assert orphan_calls == []


# ---------------------------------------------------------------------------
# Test 4: Timeout fallback continuation (on_timeout.out)
#   approval node times out but has on_timeout.out → run continues to gitlab
# ---------------------------------------------------------------------------


def test_timeout_with_on_timeout_out_continues_run(ir):
    """Timeout with on_timeout.out: approval continues as completed with synthetic output."""
    from bpg.providers.base import ExecutionHandle, ExecutionStatus

    # triage succeeds (uses agent.pipeline), approval times out (uses slack.interactive)
    triage_mock = MockProvider()
    triage_mock.register_for_node("triage", {
        "risk": "high",
        "summary": "Critical regression",
        "labels": ["critical"],
        "recommended_assignee": None,
    })

    gitlab_mock = MockProvider()
    gitlab_mock.register_for_node("gitlab", {
        "ticket_id": "PROJ-7",
        "url": "https://gitlab.example.com/issues/7",
    })

    class _TimeoutApprovalProvider(MockProvider):
        """Provider that always times out — simulates a Slack approval that never arrives."""

        def invoke(self, input, config, context):
            # Return a valid handle so the runtime proceeds to await_result
            return ExecutionHandle(
                handle_id=context.idempotency_key,
                idempotency_key=context.idempotency_key,
                provider_id=self.provider_id,
                provider_data={"status": ExecutionStatus.RUNNING},
            )

        def await_result(self, handle, timeout=None):
            raise TimeoutError("simulated approval timeout")

    timeout_approval = _TimeoutApprovalProvider()

    providers = {
        "dashboard.form": triage_mock,
        "agent.pipeline": triage_mock,
        "slack.interactive": timeout_approval,
        "http.gitlab": gitlab_mock,
    }

    runtime = LangGraphRuntime(ir=ir, providers=providers)
    final_state = runtime.run(input_payload={
        "title": "Critical regression",
        "severity": "S1",
        "description": "All tests failing.",
        "reporter_email": None,
    })

    # Approval timed out but has on_timeout.out → should be COMPLETED for routing
    approval_status = final_state["node_statuses"].get("approval")
    assert approval_status == NodeStatus.COMPLETED.value, (
        f"Expected COMPLETED (synthetic), got {approval_status}"
    )

    # approval's synthetic output should be the on_timeout.out value
    approval_output = final_state["node_outputs"].get("approval")
    assert approval_output is not None
    assert approval_output["approved"] is False

    # The execution log should record the timeout event with synthetic=True
    approval_log = [e for e in final_state["execution_log"] if e["node"] == "approval"]
    assert len(approval_log) == 1
    assert approval_log[0]["status"] == NodeStatus.TIMED_OUT.value
    assert approval_log[0].get("synthetic") is True


def test_timeout_without_on_timeout_out_stops_routing(tmp_path: Path):
    """Timeout with no on_timeout.out: node is TIMED_OUT and downstream skipped."""
    from bpg.providers.base import ExecutionHandle, ExecutionStatus

    ir = _compile_inline_process(
        tmp_path,
        """
types:
  Out:
    ok: bool
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  wait_node@v1:
    in: object
    out: Out
    provider: timeout.mock
    version: v1
    config_schema: {}
    timeout_default: 25ms
  down_node@v1:
    in: Out
    out: Out
    provider: mock
    version: v1
    config_schema: {}

nodes:
  start:
    type: trigger_node@v1
    config: {}
  wait:
    type: wait_node@v1
    config: {}
  down:
    type: down_node@v1
    config: {}

trigger: start
edges:
  - from: start
    to: wait
  - from: wait
    to: down
    with:
      ok: wait.out.ok
""",
    )

    class _TimeoutTriageProvider(MockProvider):
        """Provider that never completes; runtime timeout should terminate it."""

        def invoke(self, input, config, context):
            return ExecutionHandle(
                handle_id=context.idempotency_key,
                idempotency_key=context.idempotency_key,
                provider_id=self.provider_id,
                provider_data={"status": ExecutionStatus.RUNNING},
            )

        def poll(self, handle):
            return ExecutionStatus.RUNNING

    timeout_triage = _TimeoutTriageProvider()
    normal_mock = MockProvider()

    providers = {
        "mock": normal_mock,
        "timeout.mock": timeout_triage,
    }

    runtime = LangGraphRuntime(ir=ir, providers=providers)
    final_state = runtime.run(input_payload={})

    assert final_state["node_statuses"]["wait"] == NodeStatus.TIMED_OUT.value
    assert final_state["node_statuses"]["down"] == NodeStatus.SKIPPED.value


# ---------------------------------------------------------------------------
# Test 5: Runtime type validation
# ---------------------------------------------------------------------------


def test_trigger_input_validation_rejects_bad_payload(ir):
    """Trigger input missing required field raises ValueError."""
    runtime = LangGraphRuntime(ir=ir, providers={})

    with pytest.raises(ValueError, match="Trigger input validation failed"):
        # BugReport requires title, severity, description; omitting all
        runtime.run(input_payload={})


def test_node_output_validation_fails_node_on_bad_output(ir):
    """Provider returning output that fails type validation marks node as failed."""
    mock = MockProvider()
    # triage returns a field that should be enum(low,med,high) but isn't
    mock.register_for_node("triage", {
        "risk": "INVALID_RISK",  # not in enum(low,med,high)
        "summary": "Test",
        "labels": [],
        "recommended_assignee": None,
    })

    runtime = LangGraphRuntime(ir=ir, providers=_make_providers(mock))
    final_state = runtime.run(input_payload={
        "title": "T",
        "severity": "S1",
        "description": "D",
        "reporter_email": None,
    })

    assert final_state["node_statuses"]["triage"] == NodeStatus.FAILED.value
    triage_log = [e for e in final_state["execution_log"] if e["node"] == "triage"]
    assert any("INVALID_RISK" in e.get("error", "") or "enum" in e.get("error", "") for e in triage_log)


def test_multi_incoming_edges_merge_mappings(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
types:
  JoinIn:
    left: string
    right: string
  LeftOut:
    left: string
  RightOut:
    right: string
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  left_node@v1:
    in: object
    out: LeftOut
    provider: mock
    version: v1
    config_schema: {}
  right_node@v1:
    in: object
    out: RightOut
    provider: mock
    version: v1
    config_schema: {}
  join_node@v1:
    in: JoinIn
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  start:
    type: trigger_node@v1
    config: {}
  left:
    type: left_node@v1
    config: {}
  right:
    type: right_node@v1
    config: {}
  join:
    type: join_node@v1
    config: {}
trigger: start
edges:
  - from: start
    to: left
  - from: start
    to: right
  - from: left
    to: join
    with:
      left: left.out.left
  - from: right
    to: join
    with:
      right: right.out.right
""",
    )
    mock = MockProvider()
    mock.register_for_node("left", {"left": "L"})
    mock.register_for_node("right", {"right": "R"})
    mock.register_for_node("join", {"ok": True})
    runtime = LangGraphRuntime(ir=ir, providers={"mock": mock})
    final_state = runtime.run(input_payload={})

    assert final_state["node_statuses"]["join"] == NodeStatus.COMPLETED.value
    join_calls = [c for c in mock.calls if c.node_name == "join"]
    assert len(join_calls) == 1
    assert join_calls[0].input == {"left": "L", "right": "R"}


def test_multi_incoming_edges_conflicting_mapping_fails(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
types:
  JoinIn:
    shared: string
  OutA:
    value: string
  OutB:
    value: string
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  node_a@v1:
    in: object
    out: OutA
    provider: mock
    version: v1
    config_schema: {}
  node_b@v1:
    in: object
    out: OutB
    provider: mock
    version: v1
    config_schema: {}
  join_node@v1:
    in: JoinIn
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  start:
    type: trigger_node@v1
    config: {}
  a:
    type: node_a@v1
    config: {}
  b:
    type: node_b@v1
    config: {}
  join:
    type: join_node@v1
    config: {}
trigger: start
edges:
  - from: start
    to: a
  - from: start
    to: b
  - from: a
    to: join
    with:
      shared: a.out.value
  - from: b
    to: join
    with:
      shared: b.out.value
""",
    )
    mock = MockProvider()
    mock.register_for_node("a", {"value": "A"})
    mock.register_for_node("b", {"value": "B"})
    runtime = LangGraphRuntime(ir=ir, providers={"mock": mock})
    final_state = runtime.run(input_payload={})

    assert final_state["node_statuses"]["join"] == NodeStatus.FAILED.value
    join_calls = [c for c in mock.calls if c.node_name == "join"]
    assert join_calls == []
    assert "Conflicting mapping" in final_state["execution_log"][-1]["error"]


def _compile_inline_process(tmp_path: Path, yaml_text: str):
    path = tmp_path / "process.bpg.yaml"
    doc = yaml.safe_load(yaml_text) or {}
    if not doc.get("types"):
        doc["types"] = {"_RequiredType": {"ok": "bool"}}
    path.write_text(yaml.safe_dump(doc, sort_keys=False))
    process = parse_process_file(path)
    validate_process(process)
    return compile_process(process)


def test_access_control_policy_denies_human_node(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  approval_node@v1:
    in: object
    out: object
    provider: dashboard.form
    version: v1
    config_schema:
      timeout: duration

nodes:
  start:
    type: trigger_node@v1
    config: {}
  approval:
    type: approval_node@v1
    config:
      timeout: 1h
    on_timeout:
      out: {}

trigger: start
edges:
  - from: start
    to: approval

policy:
  access_control:
    - node: approval
      allowed_roles: [engineering_lead]
""",
    )
    mock = MockProvider()
    mock.set_default({})
    providers = {"mock": mock, "dashboard.form": mock}
    runtime = LangGraphRuntime(ir=ir, providers=providers)
    final_state = runtime.run(input_payload={})
    assert final_state["node_statuses"]["approval"] == NodeStatus.FAILED.value
    assert "Access denied" in final_state["execution_log"][-1]["error"]


def test_separation_of_duties_blocks_same_reporter_and_actor(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  approval_node@v1:
    in: object
    out: object
    provider: dashboard.form
    version: v1
    config_schema:
      timeout: duration

nodes:
  start:
    type: trigger_node@v1
    config: {}
  approval:
    type: approval_node@v1
    config:
      timeout: 1h
    on_timeout:
      out: {}

trigger: start
edges:
  - from: start
    to: approval

policy:
  separation_of_duties:
    reporter_cannot_approve: true
""",
    )
    mock = MockProvider()
    mock.set_default({})
    providers = {"mock": mock, "dashboard.form": mock}
    runtime = LangGraphRuntime(ir=ir, providers=providers)
    final_state = runtime.run(
        input_payload={"reporter_email": "a@example.com", "__actor_id__": "a@example.com"}
    )
    assert final_state["node_statuses"]["approval"] == NodeStatus.FAILED.value
    assert "Separation-of-duties" in final_state["execution_log"][-1]["error"]


def test_audit_policy_emits_run_audit_event(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}

nodes:
  start:
    type: trigger_node@v1
    config: {}

trigger: start
edges: []

policy:
  audit:
    retain_run_logs_for: 365d
    export_to: splunk.audit_sink
    tags:
      compliance: sox
      env: prod
""",
    )
    mock = MockProvider()
    mock.set_default({})
    sink = ListEventSink()
    runtime = LangGraphRuntime(ir=ir, providers={"mock": mock}, event_sink=sink)
    final_state = runtime.run(input_payload={})
    assert final_state["audit"]["retention"] == "365d"
    assert final_state["audit"]["export_to"] == "splunk.audit_sink"
    assert final_state["audit"]["tags"] == {"compliance": "sox", "env": "prod"}
    audit_events = [e for e in sink.events if e.get("event_type") == "run_audit"]
    assert len(audit_events) == 1
    assert audit_events[0].get("tags") == {"compliance": "sox", "env": "prod"}


def test_process_output_is_null_when_referenced_node_skipped(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
types:
  Decision:
    approved: bool
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  approval_node@v1:
    in: object
    out: Decision
    provider: mock
    version: v1
    config_schema: {}

nodes:
  start:
    type: trigger_node@v1
    config: {}
  approval:
    type: approval_node@v1
    config: {}

trigger: start
output: approval.out.approved
edges:
  - from: start
    to: approval
      # always false: node is skipped
    when: start.out.__never__ == true
""",
    )
    mock = MockProvider()
    mock.set_default({})
    runtime = LangGraphRuntime(ir=ir, providers={"mock": mock})
    final_state = runtime.run(input_payload={})
    assert final_state["node_statuses"]["approval"] == NodeStatus.SKIPPED.value
    assert final_state["process_output"] is None


def test_cancel_run_cancels_inflight_provider(tmp_path: Path):
    from bpg.providers.base import ExecutionContext, ExecutionHandle, ExecutionStatus, Provider, ProviderError

    class _BlockingProvider(Provider):
        provider_id = "blocking.test"

        def invoke(self, input, config, context: ExecutionContext):
            return ExecutionHandle(
                handle_id=context.idempotency_key,
                idempotency_key=context.idempotency_key,
                provider_id=self.provider_id,
                provider_data={"cancelled": False, "status": ExecutionStatus.RUNNING},
            )

        def poll(self, handle):
            return ExecutionStatus.FAILED if handle.provider_data.get("cancelled") else ExecutionStatus.RUNNING

        def await_result(self, handle, timeout=None):
            _ = timeout
            while not handle.provider_data.get("cancelled"):
                time.sleep(0.01)
            raise ProviderError(code="cancelled", message="cancelled", retryable=False)

        def cancel(self, handle):
            handle.provider_data["cancelled"] = True
            handle.provider_data["status"] = ExecutionStatus.FAILED

    ir = _compile_inline_process(
        tmp_path,
        """
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  blocking_node@v1:
    in: object
    out: object
    provider: blocking.test
    version: v1
    config_schema: {}

nodes:
  start:
    type: trigger_node@v1
    config: {}
  wait:
    type: blocking_node@v1
    config: {}

trigger: start
edges:
  - from: start
    to: wait
""",
    )
    mock = MockProvider()
    mock.set_default({})
    runtime = LangGraphRuntime(
        ir=ir,
        providers={"mock": mock, "blocking.test": _BlockingProvider()},
    )
    result: dict = {}
    run_id = "cancel-run-1"

    def _runner():
        result["state"] = runtime.run(input_payload={}, run_id=run_id)

    t = threading.Thread(target=_runner)
    t.start()
    time.sleep(0.05)
    assert runtime.cancel_run(run_id) is True
    t.join(timeout=2.0)
    assert not t.is_alive()
    final_state = result["state"]
    assert final_state["run_status"] == NodeStatus.CANCELLED.value
    assert final_state["node_statuses"]["wait"] == NodeStatus.CANCELLED.value


def test_blocking_invoke_still_honors_runtime_timeout(tmp_path: Path):
    from bpg.providers.base import ExecutionContext, ExecutionHandle, ExecutionStatus, Provider

    class _BlockingInvokeProvider(Provider):
        provider_id = "blocking.invoke"

        def invoke(self, input, config, context: ExecutionContext):
            time.sleep(0.5)
            return ExecutionHandle(
                handle_id=context.idempotency_key,
                idempotency_key=context.idempotency_key,
                provider_id=self.provider_id,
                provider_data={"status": ExecutionStatus.RUNNING},
            )

        def poll(self, handle):
            return ExecutionStatus.RUNNING

        def await_result(self, handle, timeout=None):
            _ = timeout
            return {"ok": True}

        def cancel(self, handle):
            handle.provider_data["status"] = ExecutionStatus.FAILED

    ir = _compile_inline_process(
        tmp_path,
        """
types:
  WaitOut:
    ok: bool
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  wait_node@v1:
    in: object
    out: WaitOut
    provider: blocking.invoke
    version: v1
    config_schema: {}
    timeout_default: 100ms

nodes:
  start:
    type: trigger_node@v1
    config: {}
  wait:
    type: wait_node@v1
    config: {}

trigger: start
edges:
  - from: start
    to: wait
""",
    )
    mock = MockProvider()
    mock.set_default({})
    runtime = LangGraphRuntime(
        ir=ir,
        providers={"mock": mock, "blocking.invoke": _BlockingInvokeProvider()},
    )
    t0 = time.time()
    final_state = runtime.run(input_payload={})
    elapsed = time.time() - t0
    assert elapsed < 0.4
    assert final_state["node_statuses"]["wait"] == NodeStatus.TIMED_OUT.value
    assert final_state["run_status"] == NodeStatus.FAILED.value


def test_runtime_result_cache_avoids_duplicate_provider_invocation(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
types:
  Out:
    ok: bool
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  work_node@v1:
    in: object
    out: Out
    provider: mock
    version: v1
    config_schema: {}

nodes:
  start:
    type: trigger_node@v1
    config: {}
  work:
    type: work_node@v1
    config: {}

trigger: start
edges:
  - from: start
    to: work
""",
    )
    mock = MockProvider()
    mock.set_default({"ok": True})
    runtime = LangGraphRuntime(ir=ir, providers={"mock": mock})
    run_id = "cache-run-1"
    runtime.run(input_payload={"a": 1}, run_id=run_id)
    runtime.run(input_payload={"a": 1}, run_id=run_id)
    work_calls = [c for c in mock.calls if c.node_name == "work"]
    assert len(work_calls) == 1


def test_unstable_input_fields_excluded_from_idempotency_key(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
types:
  Out:
    ok: bool
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  work_node@v1:
    in: object
    out: Out
    provider: mock
    version: v1
    config_schema: {}

nodes:
  start:
    type: trigger_node@v1
    config: {}
  work:
    type: work_node@v1
    unstable_input_fields: [timestamp]
    config: {}

trigger: start
edges:
  - from: start
    to: work
    with:
      timestamp: trigger.out.timestamp
      id: trigger.out.id
""",
    )
    mock = MockProvider()
    mock.set_default({"ok": True})
    runtime = LangGraphRuntime(ir=ir, providers={"mock": mock})
    run_id = "cache-run-unstable"
    runtime.run(input_payload={"timestamp": "2026-01-01T00:00:00Z", "id": "1"}, run_id=run_id)
    runtime.run(input_payload={"timestamp": "2026-01-02T00:00:00Z", "id": "1"}, run_id=run_id)
    work_calls = [c for c in mock.calls if c.node_name == "work"]
    assert len(work_calls) == 1


def test_advanced_separation_of_duties_rule_blocks_role_overlap(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  approval_node@v1:
    in: object
    out: object
    provider: dashboard.form
    version: v1
    config_schema:
      timeout: duration

nodes:
  start:
    type: trigger_node@v1
    config: {}
  approval:
    type: approval_node@v1
    config:
      timeout: 1h
    on_timeout:
      out: {}

trigger: start
edges:
  - from: start
    to: approval
policy:
  separation_of_duties:
    rules:
      - left_principal_field: __actor_roles__
        right_principal_field: restricted_roles
        nodes: [approval]
""",
    )
    mock = MockProvider()
    mock.set_default({})
    runtime = LangGraphRuntime(ir=ir, providers={"mock": mock, "dashboard.form": mock})
    final_state = runtime.run(
        input_payload={
            "restricted_roles": ["approver", "admin"],
            "__actor_roles__": ["developer", "approver"],
        }
    )
    assert final_state["node_statuses"]["approval"] == NodeStatus.FAILED.value
    assert "Separation-of-duties" in final_state["execution_log"][-1]["error"]


def test_edge_on_failure_route_recovers_run(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  work_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  recovery_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  start:
    type: trigger_node@v1
    config: {}
  work:
    type: work_node@v1
    config: {}
  recovery:
    type: recovery_node@v1
    config: {}
trigger: start
edges:
  - from: start
    to: work
    on_failure:
      action: route
      to: recovery
  - from: work
    to: recovery
    when: "false"
""",
    )
    mock = MockProvider()
    mock.register_error("work", ProviderError("boom", "fail work", retryable=False))
    mock.register_for_node("recovery", {"ok": True})
    runtime = LangGraphRuntime(ir=ir, providers={"mock": mock})
    final_state = runtime.run(input_payload={})

    assert final_state["node_statuses"]["work"] == NodeStatus.FAILED.value
    assert final_state["node_statuses"]["recovery"] == NodeStatus.COMPLETED.value
    assert final_state["run_status"] == NodeStatus.COMPLETED.value


def test_edge_on_failure_notify_routes_to_notification_node(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  work_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  notify_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  start:
    type: trigger_node@v1
    config: {}
  work:
    type: work_node@v1
    config: {}
  notify:
    type: notify_node@v1
    config: {}
trigger: start
edges:
  - from: start
    to: work
    on_failure:
      action: notify
      node: notify
  - from: work
    to: notify
    when: "false"
""",
    )
    mock = MockProvider()
    mock.register_error("work", ProviderError("boom", "fail work", retryable=False))
    mock.register_for_node("notify", {"sent": True})
    runtime = LangGraphRuntime(ir=ir, providers={"mock": mock})
    final_state = runtime.run(input_payload={})

    assert final_state["node_statuses"]["work"] == NodeStatus.FAILED.value
    assert final_state["node_statuses"]["notify"] == NodeStatus.COMPLETED.value
    assert final_state["run_status"] == NodeStatus.COMPLETED.value
    notify_calls = [c for c in mock.calls if c.node_name == "notify"]
    assert len(notify_calls) == 1
    assert notify_calls[0].input["__failure__"]["node"] == "work"


def test_edge_on_failure_fail_sets_terminal_failed(tmp_path: Path):
    ir = _compile_inline_process(
        tmp_path,
        """
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  work_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  recovery_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  start:
    type: trigger_node@v1
    config: {}
  work:
    type: work_node@v1
    config: {}
  recovery:
    type: recovery_node@v1
    config: {}
trigger: start
edges:
  - from: start
    to: work
    on_failure:
      action: fail
""",
    )
    mock = MockProvider()
    mock.register_error("work", ProviderError("boom", "fail work", retryable=False))
    mock.register_for_node("recovery", {"ok": True})
    runtime = LangGraphRuntime(ir=ir, providers={"mock": mock})
    final_state = runtime.run(input_payload={})

    assert final_state["node_statuses"]["work"] == NodeStatus.FAILED.value
    assert final_state["node_statuses"]["recovery"] == NodeStatus.SKIPPED.value
    assert final_state["run_status"] == NodeStatus.FAILED.value


def test_escalation_policy_routes_on_timeout(tmp_path: Path):
    from bpg.providers.base import ExecutionHandle, ExecutionStatus

    class _TimeoutProvider(MockProvider):
        def invoke(self, input, config, context):
            return ExecutionHandle(
                handle_id=context.idempotency_key,
                idempotency_key=context.idempotency_key,
                provider_id=self.provider_id,
                provider_data={"status": ExecutionStatus.RUNNING},
            )

        def await_result(self, handle, timeout=None):
            raise TimeoutError("timeout")

    ir = _compile_inline_process(
        tmp_path,
        """
types:
  Out:
    ok: bool
node_types:
  trigger_node@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
  wait_node@v1:
    in: object
    out: Out
    provider: timeout.mock
    version: v1
    config_schema: {}
    timeout_default: 50ms
  recovery_node@v1:
    in: object
    out: Out
    provider: mock
    version: v1
    config_schema: {}

nodes:
  start:
    type: trigger_node@v1
    config: {}
  wait:
    type: wait_node@v1
    config: {}
  recovery:
    type: recovery_node@v1
    config: {}

trigger: start
edges:
  - from: start
    to: wait
  - from: wait
    to: recovery
policy:
  escalation:
    - node: wait
      on: timeout
      after_attempts: 1
      route_to: recovery
""",
    )
    timeout_mock = _TimeoutProvider()
    normal_mock = MockProvider()
    normal_mock.set_default({"ok": True})
    runtime = LangGraphRuntime(
        ir=ir,
        providers={"mock": normal_mock, "timeout.mock": timeout_mock},
    )
    final_state = runtime.run(input_payload={})
    assert final_state["node_statuses"]["wait"] == NodeStatus.TIMED_OUT.value
    assert final_state["node_statuses"]["recovery"] == NodeStatus.COMPLETED.value
    assert final_state["run_status"] == NodeStatus.COMPLETED.value
