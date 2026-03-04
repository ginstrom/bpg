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
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from bpg.providers import (
    AiAnthropicProvider,
    AiGoogleProvider,
    AiLlmProvider,
    AiOllamaProvider,
    AiOpenAIProvider,
    AgentPipelineProvider,
    BpgProcessCallProvider,
    DashboardFormProvider,
    EmbedTextProvider,
    EmailNotifyProvider,
    FlowAwaitAllProvider,
    FlowFanoutProvider,
    FlowLoopProvider,
    MarkdownChunkProvider,
    MarkdownListProvider,
    HttpGitlabProvider,
    ParseTextNumbersProvider,
    PROVIDER_REGISTRY,
    QueueKafkaProvider,
    MockProvider,
    ProviderError,
    SumNumbersProvider,
    TimerDelayProvider,
    WeaviateHybridSearchProvider,
    WeaviateUpsertProvider,
    WebSearchProvider,
    WebhookProvider,
    compute_idempotency_key,
    describe_provider_metadata,
    list_provider_metadata,
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
            "ai.anthropic",
            "ai.openai",
            "ai.google",
            "ai.ollama",
            "ai.llm",
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
            "text.parse_numbers",
            "math.sum_numbers",
            "fs.markdown_list",
            "text.markdown_chunk",
            "embed.text",
            "weaviate.upsert",
            "weaviate.hybrid_search",
            "tool.web_search",
            "notify.email",
        }

    def test_registry_metadata_is_available_for_all_providers(self):
        metadata = list_provider_metadata()
        names = {item.name for item in metadata}
        assert names == set(PROVIDER_REGISTRY.keys())
        for item in metadata:
            assert item.description
            assert item.examples

    def test_describe_provider_metadata_returns_named_provider(self):
        meta = describe_provider_metadata("mock")
        assert meta.name == "mock"


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

    def test_parse_text_numbers_extracts_numeric_tokens(self):
        provider = ParseTextNumbersProvider()
        ctx = _ctx(node_name="parse")
        handle = provider.invoke({"text": "values: 4, 10.5 and -2"}, {}, ctx)
        out = provider.await_result(handle)
        assert out["numbers"] == [4.0, 10.5, -2.0]

    def test_sum_numbers_returns_total_and_count(self):
        provider = SumNumbersProvider()
        ctx = _ctx(node_name="sum")
        handle = provider.invoke({"numbers": [1, 2, 3.5]}, {}, ctx)
        out = provider.await_result(handle)
        assert out["sum"] == 6.5
        assert out["count"] == 3

    def test_web_search_dry_run(self):
        provider = WebSearchProvider()
        ctx = _ctx(node_name="search")
        handle = provider.invoke({"query": "bpg architecture"}, {"dry_run": True, "top_k": 2}, ctx)
        out = provider.await_result(handle)
        assert out["source"] == "dry-run"
        assert len(out["results"]) == 2

    def test_web_search_live_mode_calls_endpoint(self):
        provider = WebSearchProvider()
        ctx = _ctx(node_name="search")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"results":[{"title":"A","url":"https://a","snippet":"S"}]}'

        with patch("bpg.providers.builtin.urllib.request.urlopen", return_value=_Resp()):
            with patch.dict("os.environ", {"WEB_SEARCH_API_KEY": "k"}, clear=False):
                handle = provider.invoke(
                    {"query": "hello"},
                    {"endpoint": "https://search.local", "dry_run": False},
                    ctx,
                )
        out = provider.await_result(handle)
        assert out["source"] == "https://search.local"
        assert out["results"][0]["title"] == "A"

    def test_ai_llm_anthropic_live_mode_calls_endpoint_and_parses_json(self):
        provider = AiAnthropicProvider()
        ctx = _ctx(node_name="extract")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"content":[{"type":"text","text":"{\\"risk\\":\\"high\\"}"}]}'

        with patch("bpg.providers.ai.base.urllib.request.urlopen", return_value=_Resp()) as mock_urlopen:
            with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "k"}, clear=False):
                handle = provider.invoke(
                    {"text": "prod is down"},
                    {
                        "model": "claude-3-5-sonnet-latest",
                        "output_schema": {
                            "type": "object",
                            "required": ["risk"],
                            "properties": {"risk": {"type": "string"}},
                        },
                    },
                    ctx,
                )
        out = provider.await_result(handle)
        assert out["risk"] == "high"
        req = mock_urlopen.call_args.args[0]
        headers = {k.lower(): v for k, v in req.header_items()}
        assert headers["x-api-key"] == "k"
        body = json.loads(req.data.decode("utf-8"))
        assert body["model"] == "claude-3-5-sonnet-latest"
        assert body["messages"][0]["role"] == "user"

    def test_ai_llm_requires_api_key(self):
        provider = AiAnthropicProvider()
        ctx = _ctx(node_name="extract")
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ProviderError, match="missing required env ANTHROPIC_API_KEY"):
                provider.invoke(
                    {"text": "prod is down"},
                    {"model": "claude-3-5-sonnet-latest"},
                    ctx,
                )

    def test_ai_llm_rejects_output_schema_mismatch(self):
        provider = AiAnthropicProvider()
        ctx = _ctx(node_name="extract")
        with pytest.raises(ProviderError, match="output failed schema checks"):
            provider.invoke(
                {"text": "anything"},
                {
                    "model": "claude-3-5-sonnet-latest",
                    "dry_run": True,
                    "mock_output": {"risk": 10},
                    "output_schema": {
                        "type": "object",
                        "required": ["risk"],
                        "properties": {"risk": {"type": "string"}},
                    },
                },
                ctx,
            )

    def test_ai_openai_live_mode_calls_endpoint_and_parses_json(self):
        provider = AiOpenAIProvider()
        ctx = _ctx(node_name="extract")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"output":[{"content":[{"type":"output_text","text":"{\\"risk\\":\\"med\\"}"}]}]}'

        with patch("bpg.providers.ai.base.urllib.request.urlopen", return_value=_Resp()) as mock_urlopen:
            with patch.dict("os.environ", {"OPENAI_API_KEY": "k"}, clear=False):
                handle = provider.invoke({"text": "prod is down"}, {"model": "gpt-4.1-mini"}, ctx)

        out = provider.await_result(handle)
        assert out["risk"] == "med"
        req = mock_urlopen.call_args.args[0]
        headers = {k.lower(): v for k, v in req.header_items()}
        assert headers["authorization"] == "Bearer k"

    def test_ai_openai_requires_api_key(self):
        provider = AiOpenAIProvider()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ProviderError, match="missing required env OPENAI_API_KEY"):
                provider.invoke({"text": "x"}, {"model": "gpt-4.1-mini"}, _ctx(node_name="extract"))

    def test_ai_google_live_mode_calls_endpoint_and_parses_json(self):
        provider = AiGoogleProvider()
        ctx = _ctx(node_name="extract")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"candidates":[{"content":{"parts":[{"text":"{\\"risk\\":\\"low\\"}"}]}}]}'

        with patch("bpg.providers.ai.base.urllib.request.urlopen", return_value=_Resp()) as mock_urlopen:
            with patch.dict("os.environ", {"GOOGLE_API_KEY": "k"}, clear=False):
                handle = provider.invoke({"text": "prod is down"}, {"model": "gemini-1.5-flash"}, ctx)

        out = provider.await_result(handle)
        assert out["risk"] == "low"
        req = mock_urlopen.call_args.args[0]
        assert "key=k" in req.full_url

    def test_ai_google_requires_api_key(self):
        provider = AiGoogleProvider()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ProviderError, match="missing required env GOOGLE_API_KEY"):
                provider.invoke({"text": "x"}, {"model": "gemini-1.5-flash"}, _ctx(node_name="extract"))

    def test_ai_ollama_live_mode_calls_endpoint_and_parses_json(self):
        provider = AiOllamaProvider()
        ctx = _ctx(node_name="extract")

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b'{"response":"{\\"risk\\":\\"high\\"}"}'

        with patch("bpg.providers.ai.base.urllib.request.urlopen", return_value=_Resp()) as mock_urlopen:
            handle = provider.invoke({"text": "prod is down"}, {"model": "llama3.1"}, ctx)

        out = provider.await_result(handle)
        assert out["risk"] == "high"
        req = mock_urlopen.call_args.args[0]
        assert req.full_url == "http://localhost:11434/api/generate"

    def test_ai_ollama_packaging_requirements_no_required_env(self):
        provider = AiOllamaProvider()
        reqs = provider.packaging_requirements({"model": "llama3.1"})
        assert reqs["required_env"] == []
        assert reqs["optional_env"] == []

    def test_ai_llm_compatibility_alias_uses_anthropic_contract(self):
        provider = AiLlmProvider()
        with patch.dict("os.environ", {}, clear=True):
            with pytest.raises(ProviderError, match="missing required env ANTHROPIC_API_KEY"):
                provider.invoke({"text": "x"}, {"model": "claude-3-5-sonnet-latest"}, _ctx(node_name="extract"))

    def test_email_notify_dry_run(self):
        provider = EmailNotifyProvider()
        ctx = _ctx(node_name="mail")
        with patch.dict("os.environ", {"SMTP_FROM": "robot@example.com"}, clear=False):
            handle = provider.invoke(
                {"to": "user@example.com", "subject": "Hello", "body": "Hi"},
                {"dry_run": True},
                ctx,
            )
        out = provider.await_result(handle)
        assert out["dry_run"] is True
        assert out["sent"] is False

    def test_email_notify_live_mode_uses_smtp(self):
        provider = EmailNotifyProvider()
        ctx = _ctx(node_name="mail")

        class _FakeSMTP:
            def __init__(self, host, port, timeout):
                self.host = host
                self.port = port
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def starttls(self):
                return None

            def login(self, username, password):
                return None

            def send_message(self, msg):
                return None

        with patch("bpg.providers.builtin.smtplib.SMTP", _FakeSMTP):
            with patch.dict(
                "os.environ",
                {
                    "SMTP_HOST": "smtp.local",
                    "SMTP_FROM": "robot@example.com",
                    "SMTP_USERNAME": "user",
                    "SMTP_PASSWORD": "pass",
                },
                clear=False,
            ):
                handle = provider.invoke(
                    {"to": "user@example.com", "subject": "Hello", "body": "Hi"},
                    {"dry_run": False},
                    ctx,
                )
        out = provider.await_result(handle)
        assert out["dry_run"] is False
        assert out["sent"] is True

    def test_markdown_list_reads_markdown_files(self, tmp_path: Path):
        provider = MarkdownListProvider()
        ctx = _ctx(node_name="list")
        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "a.md").write_text("# Title\n\nAlpha", encoding="utf-8")
        (docs_dir / "b.txt").write_text("ignore", encoding="utf-8")

        handle = provider.invoke({"root_dir": str(docs_dir), "glob": "*.md"}, {}, ctx)
        out = provider.await_result(handle)
        assert len(out["documents"]) == 1
        assert out["documents"][0]["path"].endswith("a.md")
        assert "markdown" in out["documents"][0]

    def test_markdown_chunk_splits_documents(self):
        provider = MarkdownChunkProvider()
        ctx = _ctx(node_name="chunk")
        input_payload = {
            "documents": [
                {
                    "source_id": "doc-1",
                    "path": "a.md",
                    "markdown": "0123456789",
                    "metadata": {},
                }
            ]
        }
        handle = provider.invoke(input_payload, {"chunk_size": 4, "overlap": 1}, ctx)
        out = provider.await_result(handle)
        assert len(out["chunks"]) >= 3
        assert out["chunks"][0]["chunk_id"].startswith("doc-1:")

    def test_embed_text_generates_deterministic_vectors(self):
        provider = EmbedTextProvider()
        ctx = _ctx(node_name="embed")
        handle1 = provider.invoke({"query": "hello world"}, {}, ctx)
        out1 = provider.await_result(handle1)
        handle2 = provider.invoke({"query": "hello world"}, {}, ctx)
        out2 = provider.await_result(handle2)
        assert out1["query"] == "hello world"
        assert out1["vector"] == out2["vector"]
        assert isinstance(out1["vector"], list)
        assert len(out1["vector"]) > 0

    def test_weaviate_upsert_and_hybrid_search_local_store(self, tmp_path: Path):
        upsert = WeaviateUpsertProvider()
        search = WeaviateHybridSearchProvider()
        upsert_ctx = _ctx(node_name="upsert")
        search_ctx = _ctx(node_name="search")
        config = {"store": "search_main", "store_dir": str(tmp_path)}

        upsert_handle = upsert.invoke(
            {
                "items": [
                    {
                        "source_id": "doc1",
                        "chunk_id": "doc1:0",
                        "text": "alpha beta gamma",
                        "vector": [1.0, 0.0, 0.0],
                        "metadata": {"path": "doc1.md"},
                    },
                    {
                        "source_id": "doc2",
                        "chunk_id": "doc2:0",
                        "text": "delta epsilon",
                        "vector": [0.0, 1.0, 0.0],
                        "metadata": {"path": "doc2.md"},
                    },
                ]
            },
            config,
            upsert_ctx,
        )
        upsert_out = upsert.await_result(upsert_handle)
        assert upsert_out["inserted"] == 2

        search_handle = search.invoke(
            {
                "query": "alpha",
                "vector": [1.0, 0.0, 0.0],
                "top_k": 2,
            },
            config,
            search_ctx,
        )
        search_out = search.await_result(search_handle)
        assert search_out["query"] == "alpha"
        assert len(search_out["hits"]) >= 1
        assert search_out["hits"][0]["source_id"] == "doc1"


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
