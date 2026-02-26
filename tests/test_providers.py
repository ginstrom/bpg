"""Tests for the BPG provider abstraction layer.

Covers:
- compute_idempotency_key (§8)
- MockProvider full contract
- WebhookProvider (synchronous mode) using a local HTTP server
- PROVIDER_REGISTRY wiring
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict
from unittest.mock import patch

import pytest

from bpg.providers import (
    AgentPipelineProvider,
    BpgProcessCallProvider,
    DashboardFormProvider,
    FlowAwaitAllProvider,
    FlowFanoutProvider,
    FlowLoopProvider,
    HttpGitlabProvider,
    PROVIDER_REGISTRY,
    QueueKafkaProvider,
    MockProvider,
    ProviderError,
    TimerDelayProvider,
    WebhookProvider,
    compute_idempotency_key,
)
from bpg.providers.base import ExecutionContext, ExecutionHandle, ExecutionStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ctx(
    run_id: str = "run-1",
    node_name: str = "triage",
    input_payload: Dict[str, Any] | None = None,
    process_name: str | None = "test-process",
) -> ExecutionContext:
    key = compute_idempotency_key(run_id, node_name, input_payload or {})
    return ExecutionContext(
        run_id=run_id,
        node_name=node_name,
        idempotency_key=key,
        process_name=process_name,
    )


# ---------------------------------------------------------------------------
# compute_idempotency_key
# ---------------------------------------------------------------------------

class TestComputeIdempotencyKey:
    def test_returns_64_char_hex(self):
        key = compute_idempotency_key("run-1", "triage", {"a": 1})
        assert len(key) == 64
        assert all(c in "0123456789abcdef" for c in key)

    def test_deterministic(self):
        key1 = compute_idempotency_key("run-1", "triage", {"b": 2, "a": 1})
        key2 = compute_idempotency_key("run-1", "triage", {"a": 1, "b": 2})
        assert key1 == key2, "key must be order-independent (sorted keys)"

    def test_different_run_ids(self):
        k1 = compute_idempotency_key("run-1", "triage", {})
        k2 = compute_idempotency_key("run-2", "triage", {})
        assert k1 != k2

    def test_different_node_names(self):
        k1 = compute_idempotency_key("run-1", "triage", {})
        k2 = compute_idempotency_key("run-1", "approval", {})
        assert k1 != k2

    def test_different_inputs(self):
        k1 = compute_idempotency_key("run-1", "triage", {"risk": "low"})
        k2 = compute_idempotency_key("run-1", "triage", {"risk": "high"})
        assert k1 != k2

    def test_empty_payload(self):
        key = compute_idempotency_key("run-1", "node", {})
        assert len(key) == 64


# ---------------------------------------------------------------------------
# MockProvider
# ---------------------------------------------------------------------------

class TestMockProvider:
    def setup_method(self):
        self.mock = MockProvider()
        self.ctx = _ctx()

    def test_provider_id(self):
        assert MockProvider.provider_id == "mock"

    def test_register_by_key(self):
        output = {"risk": "low", "summary": "ok", "labels": []}
        self.mock.register(self.ctx.idempotency_key, output)
        handle = self.mock.invoke({}, {}, self.ctx)
        result = self.mock.await_result(handle)
        assert result == output

    def test_register_for_node(self):
        output = {"risk": "med", "summary": "medium", "labels": ["bug"]}
        self.mock.register_for_node("triage", output)
        handle = self.mock.invoke({}, {}, self.ctx)
        result = self.mock.await_result(handle)
        assert result == output

    def test_set_default(self):
        output = {"risk": "high", "summary": "critical", "labels": ["urgent"]}
        self.mock.set_default(output)
        handle = self.mock.invoke({}, {}, self.ctx)
        result = self.mock.await_result(handle)
        assert result == output

    def test_key_takes_precedence_over_node(self):
        key_output = {"risk": "low", "summary": "by key", "labels": []}
        node_output = {"risk": "high", "summary": "by node", "labels": []}
        self.mock.register(self.ctx.idempotency_key, key_output)
        self.mock.register_for_node("triage", node_output)
        handle = self.mock.invoke({}, {}, self.ctx)
        assert self.mock.await_result(handle) == key_output

    def test_node_takes_precedence_over_default(self):
        node_output = {"risk": "med", "summary": "by node", "labels": []}
        default_output = {"risk": "low", "summary": "default", "labels": []}
        self.mock.register_for_node("triage", node_output)
        self.mock.set_default(default_output)
        handle = self.mock.invoke({}, {}, self.ctx)
        assert self.mock.await_result(handle) == node_output

    def test_no_registration_raises_provider_error(self):
        with pytest.raises(ProviderError) as exc_info:
            self.mock.invoke({}, {}, self.ctx)
        assert exc_info.value.code == "no_canned_output"

    def test_register_error(self):
        err = ProviderError(code="rate_limit", message="try later", retryable=True)
        self.mock.register_error("triage", err)
        handle = self.mock.invoke({}, {}, self.ctx)
        assert self.mock.poll(handle) == ExecutionStatus.FAILED
        with pytest.raises(ProviderError) as exc_info:
            self.mock.await_result(handle)
        assert exc_info.value.code == "rate_limit"
        assert exc_info.value.retryable is True

    def test_poll_returns_completed(self):
        self.mock.set_default({"result": "done"})
        handle = self.mock.invoke({}, {}, self.ctx)
        assert self.mock.poll(handle) == ExecutionStatus.COMPLETED

    def test_cancel_marks_failed(self):
        self.mock.set_default({"result": "done"})
        handle = self.mock.invoke({}, {}, self.ctx)
        self.mock.cancel(handle)
        assert self.mock.poll(handle) == ExecutionStatus.FAILED

    def test_records_calls(self):
        self.mock.set_default({"x": 1})
        input_payload = {"title": "crash", "severity": "S1"}
        self.mock.invoke(input_payload, {"cfg": "val"}, self.ctx)
        assert len(self.mock.calls) == 1
        rec = self.mock.calls[0]
        assert rec.node_name == "triage"
        assert rec.run_id == "run-1"
        assert rec.input == input_payload

    def test_reset_clears_state(self):
        self.mock.set_default({"x": 1})
        self.mock.invoke({}, {}, self.ctx)
        self.mock.reset()
        assert len(self.mock.calls) == 0
        assert self.mock._default is None
        with pytest.raises(ProviderError):
            self.mock.invoke({}, {}, self.ctx)

    def test_await_result_ignores_timeout(self):
        """timeout param accepted but not enforced in mock."""
        self.mock.set_default({"fast": True})
        handle = self.mock.invoke({}, {}, self.ctx)
        result = self.mock.await_result(handle, timeout=0.001)
        assert result == {"fast": True}

    def test_await_alias_delegates_to_await_result(self):
        self.mock.set_default({"fast": True})
        handle = self.mock.invoke({}, {}, self.ctx)
        result = self.mock.await_(handle, timeout=0.001)
        assert result == {"fast": True}

    def test_handle_carries_idempotency_key(self):
        self.mock.set_default({"x": 1})
        handle = self.mock.invoke({}, {}, self.ctx)
        assert handle.idempotency_key == self.ctx.idempotency_key
        assert handle.handle_id == self.ctx.idempotency_key

    def test_provider_id_on_handle(self):
        self.mock.set_default({"x": 1})
        handle = self.mock.invoke({}, {}, self.ctx)
        assert handle.provider_id == "mock"


# ---------------------------------------------------------------------------
# WebhookProvider — synchronous mode (tested with a local HTTP server)
# ---------------------------------------------------------------------------

class _SyncHandler(BaseHTTPRequestHandler):
    """Echoes back a fixed JSON response and records the last request."""

    response_body: Dict[str, Any] = {"status": "ok", "ticket_id": "BUG-42"}
    last_request: Dict[str, Any] = {}
    response_status: int = 200

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(length)
        _SyncHandler.last_request = {
            "headers": {k.lower(): v for k, v in self.headers.items()},
            "body": json.loads(body) if body else {},
        }
        payload = json.dumps(self.response_body).encode()
        self.send_response(self.response_status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        pass  # Silence server logs during tests


@pytest.fixture(scope="module")
def sync_server():
    """Start a local HTTP server for webhook tests."""
    server = HTTPServer(("127.0.0.1", 0), _SyncHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    server.shutdown()


class TestWebhookProviderSync:
    def setup_method(self):
        self.provider = WebhookProvider()
        _SyncHandler.response_body = {"status": "ok", "ticket_id": "BUG-42"}
        _SyncHandler.response_status = 200

    def test_provider_id(self):
        assert WebhookProvider.provider_id == "http.webhook"

    def test_sync_invoke_returns_completed_handle(self, sync_server):
        ctx = _ctx()
        config = {"url": sync_server}
        handle = self.provider.invoke({}, config, ctx)
        assert handle.provider_id == "http.webhook"
        assert self.provider.poll(handle) == ExecutionStatus.COMPLETED

    def test_sync_await_result(self, sync_server):
        ctx = _ctx()
        config = {"url": sync_server}
        handle = self.provider.invoke({"severity": "S1"}, config, ctx)
        result = self.provider.await_result(handle)
        assert result == {"status": "ok", "ticket_id": "BUG-42"}

    def test_idempotency_key_in_header(self, sync_server):
        ctx = _ctx()
        config = {"url": sync_server}
        self.provider.invoke({}, config, ctx)
        assert _SyncHandler.last_request["headers"]["x-idempotency-key"] == ctx.idempotency_key

    def test_input_payload_in_body(self, sync_server):
        ctx = _ctx()
        config = {"url": sync_server}
        payload = {"title": "crash", "severity": "S2"}
        self.provider.invoke(payload, config, ctx)
        assert _SyncHandler.last_request["body"] == payload

    def test_extra_headers_forwarded(self, sync_server):
        ctx = _ctx()
        config = {"url": sync_server, "headers": {"X-Custom": "hello"}}
        self.provider.invoke({}, config, ctx)
        assert _SyncHandler.last_request["headers"]["x-custom"] == "hello"

    def test_missing_url_raises_provider_error(self):
        ctx = _ctx()
        with pytest.raises(ProviderError) as exc_info:
            self.provider.invoke({}, {}, ctx)
        assert exc_info.value.code == "invalid_config"

    def test_http_500_raises_retryable_error(self, sync_server):
        _SyncHandler.response_status = 500
        _SyncHandler.response_body = {"message": "internal error"}
        ctx = _ctx()
        config = {"url": sync_server}
        with pytest.raises(ProviderError) as exc_info:
            self.provider.invoke({}, config, ctx)
        assert exc_info.value.code == "http_500"
        assert exc_info.value.retryable is True

    def test_http_404_raises_non_retryable_error(self, sync_server):
        _SyncHandler.response_status = 404
        _SyncHandler.response_body = {}
        ctx = _ctx()
        config = {"url": sync_server}
        with pytest.raises(ProviderError) as exc_info:
            self.provider.invoke({}, config, ctx)
        assert exc_info.value.retryable is False

    def test_cancel_no_cancel_url_is_noop(self, sync_server):
        ctx = _ctx()
        config = {"url": sync_server}
        handle = self.provider.invoke({}, config, ctx)
        # Should not raise
        self.provider.cancel(handle)


# ---------------------------------------------------------------------------
# WebhookProvider — asynchronous mode
# ---------------------------------------------------------------------------

class TestWebhookProviderAsync:
    """Test async mode using mocked HTTP calls."""

    def _make_provider(self):
        return WebhookProvider()

    def test_async_invoke_stores_job_id(self):
        provider = self._make_provider()
        ctx = _ctx()
        config = {"url": "http://example.com/jobs", "async_mode": True, "poll_url": "http://example.com/jobs"}

        with patch.object(
            provider.__class__,
            "invoke",
            wraps=lambda self, input, config, context: _async_invoke(provider, input, config, context),
        ):
            pass

        # Manually call _http_post and construct handle to test async path
        import bpg.providers.webhook as wh

        post_response = {"job_id": "job-abc"}
        with patch.object(wh, "_http_post", return_value=post_response):
            handle = provider.invoke({}, config, ctx)

        assert handle.provider_data["job_id"] == "job-abc"
        assert handle.provider_data["status"] == ExecutionStatus.RUNNING

    def test_async_await_result_polls_until_done(self):
        provider = self._make_provider()
        ctx = _ctx()
        config = {
            "url": "http://example.com/jobs",
            "async_mode": True,
            "poll_url": "http://example.com/jobs",
        }

        import bpg.providers.webhook as wh

        # POST returns a job_id
        with patch.object(wh, "_http_post", return_value={"job_id": "job-xyz"}):
            handle = provider.invoke({}, config, ctx)

        # Inject poll_url into handle so poll() can find it
        handle.provider_data["poll_url"] = "http://example.com/jobs"

        # Poll responses: first running, then completed
        poll_responses = [
            {"status": "running"},
            {"status": "completed", "output": {"ticket_id": "BUG-99", "url": "http://x"}},
        ]

        with patch.object(wh, "_http_get", side_effect=poll_responses):
            with patch("time.sleep"):  # Don't actually sleep in tests
                result = provider.await_result(handle, timeout=10.0)

        assert result == {"ticket_id": "BUG-99", "url": "http://x"}

    def test_async_await_result_raises_on_failure(self):
        provider = self._make_provider()
        ctx = _ctx()
        config = {
            "url": "http://example.com/jobs",
            "async_mode": True,
            "poll_url": "http://example.com/jobs",
        }

        import bpg.providers.webhook as wh

        with patch.object(wh, "_http_post", return_value={"job_id": "job-err"}):
            handle = provider.invoke({}, config, ctx)

        handle.provider_data["poll_url"] = "http://example.com/jobs"

        failed_response = {
            "status": "failed",
            "error": {"code": "upstream_error", "message": "service down", "retryable": True},
        }
        with patch.object(wh, "_http_get", return_value=failed_response):
            with pytest.raises(ProviderError) as exc_info:
                provider.await_result(handle)

        assert exc_info.value.code == "upstream_error"
        assert exc_info.value.retryable is True

    def test_async_missing_job_id_raises_error(self):
        provider = self._make_provider()
        ctx = _ctx()
        config = {"url": "http://example.com/jobs", "async_mode": True}

        import bpg.providers.webhook as wh

        with patch.object(wh, "_http_post", return_value={"no_job_id": True}):
            with pytest.raises(ProviderError) as exc_info:
                provider.invoke({}, config, ctx)

        assert exc_info.value.code == "invalid_response"


# ---------------------------------------------------------------------------
# PROVIDER_REGISTRY
# ---------------------------------------------------------------------------

class TestProviderRegistry:
    def test_mock_registered(self):
        assert "mock" in PROVIDER_REGISTRY
        assert PROVIDER_REGISTRY["mock"] is MockProvider

    def test_webhook_registered(self):
        assert "http.webhook" in PROVIDER_REGISTRY
        assert PROVIDER_REGISTRY["http.webhook"] is WebhookProvider

    def test_instantiate_from_registry(self):
        cls = PROVIDER_REGISTRY["mock"]
        provider = cls()
        assert isinstance(provider, MockProvider)

    def test_registry_contains_only_expected_entries(self):
        assert set(PROVIDER_REGISTRY.keys()) == {
            "mock",
            "http.webhook",
            "slack.interactive",
            "agent.pipeline",
            "dashboard.form",
            "http.gitlab",
            "timer.delay",
            "queue.kafka",
            "core.passthrough",
            "flow.loop",
            "flow.fanout",
            "flow.await_all",
            "bpg.process_call",
        }


class TestBuiltInProviders:
    def test_agent_pipeline_returns_structured_output(self):
        provider = AgentPipelineProvider()
        ctx = _ctx(node_name="triage")
        handle = provider.invoke({"title": "Login broken", "severity": "S1"}, {}, ctx)
        out = provider.await_result(handle)
        assert out["risk"] == "high"
        assert out["summary"] == "Login broken"

    def test_dashboard_form_merges_defaults(self):
        provider = DashboardFormProvider()
        ctx = _ctx(node_name="intake")
        handle = provider.invoke({"title": "Bug"}, {"defaults": {"approved": False}}, ctx)
        out = provider.await_result(handle)
        assert out == {"approved": False, "title": "Bug"}

    def test_http_gitlab_returns_ticket_id(self):
        provider = HttpGitlabProvider()
        ctx = _ctx(node_name="gitlab")
        handle = provider.invoke({}, {"ticket_prefix": "SEC"}, ctx)
        out = provider.await_result(handle)
        assert out["ticket_id"].startswith("SEC-")
        assert "url" in out

    def test_queue_kafka_requires_topic(self):
        provider = QueueKafkaProvider()
        ctx = _ctx(node_name="publish")
        with pytest.raises(ProviderError, match="requires a topic"):
            provider.invoke({}, {}, ctx)

    def test_timer_delay_timeout(self):
        provider = TimerDelayProvider()
        ctx = _ctx(node_name="wait")
        handle = provider.invoke({}, {"duration": 1}, ctx)
        with pytest.raises(TimeoutError):
            provider.await_result(handle, timeout=0.01)

    def test_flow_loop_applies_max_iterations(self):
        provider = FlowLoopProvider()
        ctx = _ctx(node_name="loop")
        handle = provider.invoke({"items": [1, 2, 3, 4]}, {"max_iterations": 2}, ctx)
        out = provider.await_result(handle)
        assert out["items"] == [1, 2]
        assert out["truncated"] is True

    def test_flow_fanout_builds_branches(self):
        provider = FlowFanoutProvider()
        ctx = _ctx(node_name="fanout")
        handle = provider.invoke({"items": ["a", "b"]}, {}, ctx)
        out = provider.await_result(handle)
        assert out["count"] == 2
        assert out["branches"][1]["item"] == "b"

    def test_flow_await_all_returns_aggregate(self):
        provider = FlowAwaitAllProvider()
        ctx = _ctx(node_name="await_all")
        handle = provider.invoke({"results": [{"ok": True}, {"ok": False}]}, {}, ctx)
        out = provider.await_result(handle)
        assert out["count"] == 2
        assert out["results"][0]["ok"] is True

    def test_process_call_requires_process_name(self):
        provider = BpgProcessCallProvider()
        ctx = _ctx(node_name="call")
        with pytest.raises(ProviderError, match="requires config.process_name"):
            provider.invoke({}, {}, ctx)


# ---------------------------------------------------------------------------
# ExecutionHandle and ProviderError
# ---------------------------------------------------------------------------

class TestExecutionHandle:
    def test_default_provider_data_is_empty(self):
        h = ExecutionHandle(
            handle_id="h1",
            idempotency_key="k1",
            provider_id="mock",
        )
        assert h.provider_data == {}

    def test_provider_data_is_mutable(self):
        h = ExecutionHandle(handle_id="h1", idempotency_key="k1", provider_id="mock")
        h.provider_data["status"] = ExecutionStatus.COMPLETED
        assert h.provider_data["status"] == ExecutionStatus.COMPLETED


class TestProviderError:
    def test_str_representation(self):
        err = ProviderError(code="rate_limit", message="too many requests")
        assert str(err) == "[rate_limit] too many requests"

    def test_retryable_default_false(self):
        err = ProviderError(code="x", message="y")
        assert err.retryable is False

    def test_is_exception(self):
        err = ProviderError(code="x", message="y")
        with pytest.raises(ProviderError):
            raise err


# ---------------------------------------------------------------------------
# Helper used in async test
# ---------------------------------------------------------------------------

def _async_invoke(provider, input, config, context):
    """Thin wrapper to exercise async invoke path."""
    return provider.invoke(input, config, context)
