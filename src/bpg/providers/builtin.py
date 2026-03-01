"""Built-in providers for common BPG node types.

These are pragmatic baseline implementations that are deterministic and
self-contained, so processes can run locally without custom integrations.
"""

from __future__ import annotations

import hashlib
import os
import re
import smtplib
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Any, Dict, Optional

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
    ProviderError,
)


def _is_dry_run(config: Dict[str, Any]) -> bool:
    raw = config.get("dry_run")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    mode = os.getenv("BPG_EXECUTION_MODE", "").strip().lower()
    if mode in {"dry-run", "dry_run"}:
        return True
    return os.getenv("BPG_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}


class AgentPipelineProvider(Provider):
    """`agent.pipeline` provider.

    Baseline behavior:
    - `config.mock_output` (dict) can force an exact output payload.
    - Otherwise derive a lightweight triage-style output from input fields.
    """

    provider_id = "agent.pipeline"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
        )

        output = config.get("mock_output")
        if output is None:
            severity = str(input.get("severity", "")).upper()
            risk = "high" if severity in {"S1", "P0"} else "med" if severity in {"S2", "P1"} else "low"
            title = str(input.get("title", "")).strip() or "No title"
            output = {
                "risk": risk,
                "summary": title,
                "labels": list(input.get("labels", [])) if isinstance(input.get("labels"), list) else [],
            }

        if not isinstance(output, dict):
            raise ProviderError(
                code="invalid_config",
                message="agent.pipeline expects config.mock_output to be an object",
                retryable=False,
            )

        handle.provider_data["status"] = ExecutionStatus.COMPLETED
        handle.provider_data["output"] = output
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        if handle.provider_data.get("cancelled"):
            raise ProviderError(code="cancelled", message="Invocation was cancelled", retryable=False)
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["cancelled"] = True
        handle.provider_data["status"] = ExecutionStatus.FAILED


class DashboardFormProvider(Provider):
    """`dashboard.form` provider.

    Baseline behavior merges input payload with optional `config.defaults`.
    """

    provider_id = "dashboard.form"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        defaults = config.get("defaults", {})
        if defaults is not None and not isinstance(defaults, dict):
            raise ProviderError(
                code="invalid_config",
                message="dashboard.form expects config.defaults to be an object",
                retryable=False,
            )
        output = dict(defaults or {})
        output.update(input)

        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.COMPLETED,
                "output": output,
            },
        )
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        if handle.provider_data.get("cancelled"):
            raise ProviderError(code="cancelled", message="Invocation was cancelled", retryable=False)
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["cancelled"] = True
        handle.provider_data["status"] = ExecutionStatus.FAILED


class HttpGitlabProvider(Provider):
    """`http.gitlab` provider.

    Baseline behavior returns deterministic issue metadata for local testing.
    """

    provider_id = "http.gitlab"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        prefix = str(config.get("ticket_prefix", "BPG"))
        issue_num = int(hashlib.sha256(context.idempotency_key.encode()).hexdigest()[:8], 16) % 100000
        ticket_id = config.get("ticket_id") or f"{prefix}-{issue_num:05d}"
        output = {
            "ticket_id": ticket_id,
            "url": str(config.get("issue_url", f"https://gitlab.local/issues/{ticket_id}")),
        }

        # Optional passthrough labels from input if the receiving type declares it.
        if isinstance(input.get("labels"), list):
            output["labels"] = input["labels"]

        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.COMPLETED,
                "output": output,
            },
        )
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        if handle.provider_data.get("cancelled"):
            raise ProviderError(code="cancelled", message="Invocation was cancelled", retryable=False)
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["cancelled"] = True
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        _ = config
        return {
            "services": [],
            "required_env": ["GITLAB_TOKEN"],
            "optional_env": ["GITLAB_BASE_URL"],
        }


class QueueKafkaProvider(Provider):
    """`queue.kafka` provider.

    Simulates publishing to Kafka and returns publish metadata.
    """

    provider_id = "queue.kafka"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        topic = config.get("topic") or input.get("topic")
        if not topic:
            raise ProviderError(
                code="invalid_config",
                message="queue.kafka requires a topic in config.topic or input.topic",
                retryable=False,
            )

        output = {
            "published": True,
            "topic": str(topic),
            "partition": int(config.get("partition", 0)),
            "offset": int(config.get("offset", 0)),
            "idempotency_key": context.idempotency_key,
        }
        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.COMPLETED,
                "output": output,
            },
        )
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        if handle.provider_data.get("cancelled"):
            raise ProviderError(code="cancelled", message="Invocation was cancelled", retryable=False)
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["cancelled"] = True
        handle.provider_data["status"] = ExecutionStatus.FAILED


class TimerDelayProvider(Provider):
    """`timer.delay` provider.

    Waits for the configured duration and returns a small timing payload.
    """

    provider_id = "timer.delay"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        duration = config.get("duration", input.get("duration", 0))
        try:
            duration_s = float(duration)
        except (TypeError, ValueError):
            raise ProviderError(
                code="invalid_config",
                message="timer.delay requires numeric duration seconds",
                retryable=False,
            )
        if duration_s < 0:
            raise ProviderError(
                code="invalid_config",
                message="timer.delay duration must be >= 0",
                retryable=False,
            )

        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.RUNNING,
                "duration_seconds": duration_s,
                "started_at": time.monotonic(),
            },
        )
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        if handle.provider_data.get("cancelled"):
            return ExecutionStatus.FAILED
        duration_s = float(handle.provider_data.get("duration_seconds", 0.0))
        started_at = float(handle.provider_data.get("started_at", time.monotonic()))
        if time.monotonic() - started_at >= duration_s:
            handle.provider_data["status"] = ExecutionStatus.COMPLETED
        return handle.provider_data.get("status", ExecutionStatus.RUNNING)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        if handle.provider_data.get("cancelled"):
            raise ProviderError(code="cancelled", message="Invocation was cancelled", retryable=False)

        duration_s = float(handle.provider_data.get("duration_seconds", 0.0))
        started_at = float(handle.provider_data.get("started_at", time.monotonic()))
        elapsed = max(0.0, time.monotonic() - started_at)
        remaining = max(0.0, duration_s - elapsed)

        if timeout is not None and remaining > timeout:
            time.sleep(timeout)
            raise TimeoutError("timer.delay exceeded timeout")

        if remaining > 0:
            time.sleep(remaining)

        handle.provider_data["status"] = ExecutionStatus.COMPLETED
        return {"ok": True, "slept_seconds": duration_s}

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["cancelled"] = True
        handle.provider_data["status"] = ExecutionStatus.FAILED


class FlowLoopProvider(Provider):
    """`flow.loop` provider.

    Produces a bounded slice of `input.items` for deterministic iteration plans.
    """

    provider_id = "flow.loop"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        items = input.get("items", [])
        if not isinstance(items, list):
            raise ProviderError("invalid_input", "flow.loop expects input.items list", False)
        max_iterations = config.get("max_iterations", input.get("max_iterations", len(items)))
        try:
            bound = max(0, int(max_iterations))
        except (TypeError, ValueError):
            raise ProviderError("invalid_config", "flow.loop max_iterations must be an integer", False)
        bounded = items[:bound]
        output = {
            "items": bounded,
            "count": len(bounded),
            "truncated": len(items) > len(bounded),
        }
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class FlowFanoutProvider(Provider):
    """`flow.fanout` provider.

    Converts a list payload into branch envelopes for downstream processing.
    """

    provider_id = "flow.fanout"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        _ = config
        items = input.get("items", [])
        if not isinstance(items, list):
            raise ProviderError("invalid_input", "flow.fanout expects input.items list", False)
        branches = [{"index": i, "item": item} for i, item in enumerate(items)]
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.COMPLETED,
                "output": {"branches": branches, "count": len(branches)},
            },
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class FlowAwaitAllProvider(Provider):
    """`flow.await_all` provider.

    Aggregates fanout branch results back into a single list.
    """

    provider_id = "flow.await_all"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        _ = config
        results = input.get("results", [])
        if not isinstance(results, list):
            raise ProviderError("invalid_input", "flow.await_all expects input.results list", False)
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.COMPLETED,
                "output": {"results": results, "count": len(results)},
            },
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class BpgProcessCallProvider(Provider):
    """`bpg.process_call` provider.

    Triggers another deployed BPG process and returns child run metadata.
    """

    provider_id = "bpg.process_call"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        from pathlib import Path

        from bpg.runtime.engine import Engine
        from bpg.state.store import StateStore

        process_name = config.get("process_name")
        if not isinstance(process_name, str) or not process_name:
            raise ProviderError(
                code="invalid_config",
                message="bpg.process_call requires config.process_name",
                retryable=False,
            )
        state_dir = Path(str(config.get("state_dir", ".bpg-state")))
        store = StateStore(state_dir)
        process = store.load_process(process_name)
        if process is None:
            raise ProviderError(
                code="invalid_config",
                message=f"bpg.process_call target process {process_name!r} not found",
                retryable=False,
            )
        child_run_id = Engine(process=process, state_store=store).trigger(input)
        child_run = store.load_run(child_run_id) or {}
        output = {
            "child_process": process_name,
            "child_run_id": child_run_id,
            "status": child_run.get("status", "unknown"),
            "output": child_run.get("output"),
        }
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class ParseTextNumbersProvider(Provider):
    """`text.parse_numbers` provider.

    Extracts numeric tokens from ``input.text`` and returns them as a list.
    """

    provider_id = "text.parse_numbers"
    _NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        _ = config
        text = input.get("text")
        if not isinstance(text, str):
            raise ProviderError(
                code="invalid_input",
                message="text.parse_numbers requires input.text string",
                retryable=False,
            )

        matches = self._NUMBER_RE.findall(text)
        numbers: list[float] = [float(token) for token in matches]
        output = {"numbers": numbers}
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(
        self, handle: ExecutionHandle, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class SumNumbersProvider(Provider):
    """`math.sum_numbers` provider.

    Sums ``input.numbers`` and returns ``sum`` plus ``count``.
    """

    provider_id = "math.sum_numbers"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        _ = config
        numbers = input.get("numbers")
        if not isinstance(numbers, list):
            raise ProviderError(
                code="invalid_input",
                message="math.sum_numbers requires input.numbers list",
                retryable=False,
            )
        for idx, value in enumerate(numbers):
            if not isinstance(value, (int, float)):
                raise ProviderError(
                    code="invalid_input",
                    message=f"math.sum_numbers input.numbers[{idx}] must be numeric",
                    retryable=False,
                )
        total = float(sum(numbers))
        output = {"sum": total, "count": len(numbers)}
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(
        self, handle: ExecutionHandle, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class WebSearchProvider(Provider):
    """`tool.web_search` provider.

    Dry run:
    - Returns deterministic placeholder results without external calls.
    Live mode:
    - Calls a configurable HTTP endpoint and normalizes JSON search results.
    """

    provider_id = "tool.web_search"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        query = input.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ProviderError(
                code="invalid_input",
                message="tool.web_search requires input.query string",
                retryable=False,
            )

        top_k_raw = config.get("top_k", input.get("top_k", 5))
        try:
            top_k = max(1, int(top_k_raw))
        except (TypeError, ValueError):
            raise ProviderError(
                code="invalid_config",
                message="tool.web_search top_k must be an integer",
                retryable=False,
            )

        if _is_dry_run(config):
            results = []
            for idx in range(top_k):
                n = idx + 1
                results.append({
                    "title": f"Dry-run result {n} for: {query}",
                    "url": f"https://example.invalid/search/{n}",
                    "snippet": f"Synthetic search result {n} for query '{query}'.",
                })
            output = {"query": query, "results": results, "source": "dry-run"}
        else:
            endpoint = config.get("endpoint") or os.getenv("WEB_SEARCH_ENDPOINT")
            if not isinstance(endpoint, str) or not endpoint.strip():
                raise ProviderError(
                    code="invalid_config",
                    message="tool.web_search requires config.endpoint or WEB_SEARCH_ENDPOINT in live mode",
                    retryable=False,
                )

            api_key_env = str(config.get("api_key_env", "WEB_SEARCH_API_KEY"))
            require_api_key = bool(config.get("require_api_key", True))
            api_key = os.getenv(api_key_env)
            if require_api_key and not api_key:
                raise ProviderError(
                    code="invalid_config",
                    message=f"tool.web_search missing required env {api_key_env}",
                    retryable=False,
                )

            timeout = float(config.get("timeout_seconds", 10))
            params = {"q": query, "k": str(top_k)}
            req_url = f"{endpoint}?{urllib.parse.urlencode(params)}"
            headers = {"Accept": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            req = urllib.request.Request(req_url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = resp.read().decode("utf-8")
            except Exception as exc:
                raise ProviderError(
                    code="web_search_http_error",
                    message=str(exc),
                    retryable=True,
                )

            import json

            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    code="web_search_invalid_json",
                    message=str(exc),
                    retryable=False,
                )

            raw_results = parsed.get("results") if isinstance(parsed, dict) else parsed
            if not isinstance(raw_results, list):
                raise ProviderError(
                    code="web_search_invalid_response",
                    message="tool.web_search expected response list or {results: [...]}",
                    retryable=False,
                )
            results = []
            for item in raw_results[:top_k]:
                if not isinstance(item, dict):
                    continue
                results.append({
                    "title": str(item.get("title", "")),
                    "url": str(item.get("url", "")),
                    "snippet": str(item.get("snippet", item.get("description", ""))),
                })
            output = {"query": query, "results": results, "source": endpoint}

        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(
        self, handle: ExecutionHandle, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        if _is_dry_run(config):
            return {
                "services": [],
                "required_env": [],
                "optional_env": ["WEB_SEARCH_ENDPOINT", "WEB_SEARCH_API_KEY"],
            }
        api_key_env = str(config.get("api_key_env", "WEB_SEARCH_API_KEY"))
        require_api_key = bool(config.get("require_api_key", True))
        required = [api_key_env] if require_api_key else []
        optional = [] if require_api_key else [api_key_env]
        optional.append("WEB_SEARCH_ENDPOINT")
        return {"services": [], "required_env": required, "optional_env": optional}


class EmailNotifyProvider(Provider):
    """`notify.email` provider.

    Dry run:
    - Produces synthetic delivery metadata without sending mail.
    Live mode:
    - Sends via SMTP using config/env credentials.
    """

    provider_id = "notify.email"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        to_addr = input.get("to")
        subject = input.get("subject")
        body = input.get("body")
        if not isinstance(to_addr, str) or "@" not in to_addr:
            raise ProviderError("invalid_input", "notify.email requires input.to email", False)
        if not isinstance(subject, str):
            raise ProviderError("invalid_input", "notify.email requires input.subject string", False)
        if not isinstance(body, str):
            raise ProviderError("invalid_input", "notify.email requires input.body string", False)

        from_addr = config.get("from") or os.getenv("SMTP_FROM")
        if not isinstance(from_addr, str) or "@" not in from_addr:
            raise ProviderError(
                code="invalid_config",
                message="notify.email requires config.from or SMTP_FROM",
                retryable=False,
            )

        if _is_dry_run(config):
            output = {
                "sent": False,
                "dry_run": True,
                "to": to_addr,
                "from": from_addr,
                "subject": subject,
                "message_id": f"dry-{context.idempotency_key[:16]}",
            }
        else:
            host = config.get("smtp_host") or os.getenv("SMTP_HOST")
            if not isinstance(host, str) or not host.strip():
                raise ProviderError(
                    code="invalid_config",
                    message="notify.email requires config.smtp_host or SMTP_HOST in live mode",
                    retryable=False,
                )

            port_raw = config.get("smtp_port", os.getenv("SMTP_PORT", "587"))
            try:
                port = int(port_raw)
            except (TypeError, ValueError):
                raise ProviderError(
                    code="invalid_config",
                    message="notify.email SMTP port must be an integer",
                    retryable=False,
                )
            username = config.get("smtp_username") or os.getenv("SMTP_USERNAME")
            password = config.get("smtp_password") or os.getenv("SMTP_PASSWORD")
            starttls = bool(config.get("smtp_starttls", True))

            msg = EmailMessage()
            msg["From"] = from_addr
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg["X-BPG-Idempotency-Key"] = context.idempotency_key
            msg.set_content(body)

            try:
                with smtplib.SMTP(host=host, port=port, timeout=10) as client:
                    if starttls:
                        client.starttls()
                    if username:
                        client.login(username, password or "")
                    client.send_message(msg)
            except Exception as exc:
                raise ProviderError(
                    code="smtp_send_error",
                    message=str(exc),
                    retryable=True,
                )

            output = {
                "sent": True,
                "dry_run": False,
                "to": to_addr,
                "from": from_addr,
                "subject": subject,
                "message_id": f"smtp-{context.idempotency_key[:16]}",
            }

        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(
        self, handle: ExecutionHandle, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        required: list[str] = []
        optional: list[str] = ["SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD"]
        if not config.get("from"):
            required.append("SMTP_FROM")
        else:
            optional.append("SMTP_FROM")
        if _is_dry_run(config):
            optional.append("SMTP_HOST")
            return {"services": [], "required_env": required, "optional_env": optional}
        required.append("SMTP_HOST")
        return {
            "services": [],
            "required_env": required,
            "optional_env": optional,
        }
