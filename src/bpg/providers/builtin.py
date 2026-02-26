"""Built-in providers for common BPG node types.

These are pragmatic baseline implementations that are deterministic and
self-contained, so processes can run locally without custom integrations.
"""

from __future__ import annotations

import hashlib
import time
from typing import Any, Dict, Optional

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
    ProviderError,
)


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
