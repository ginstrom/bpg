"""mock provider — returns canned outputs for testing and local development.

The mock provider lets you exercise the full provider contract (invoke / poll /
await_result / cancel) without any real external integrations.  Outputs are
registered in advance and looked up when a node is invoked.

Lookup order
------------
1. Exact idempotency key (set via ``register``)
2. Node name (set via ``register_for_node``)
3. Global default (set via ``set_default``)
4. ``ProviderError`` with code ``"no_canned_output"`` if nothing matches

Usage
-----
::

    mock = MockProvider()

    # Register by exact idempotency key (deterministic in tests)
    key = compute_idempotency_key(run_id, "triage", input_payload)
    mock.register(key, {"risk": "low", "summary": "Minor UI glitch", "labels": []})

    # Or register by node name (simpler for most tests)
    mock.register_for_node("triage", {"risk": "low", "summary": "Minor UI glitch", "labels": []})

    # Or set a blanket default for all invocations
    mock.set_default({"risk": "low", "summary": "Minor UI glitch", "labels": []})

    # Optionally simulate a failure
    mock.register_error("triage", ProviderError(code="rate_limit", message="try again", retryable=True))

Invocation recording
--------------------
Every ``invoke`` call is appended to ``mock.calls`` so tests can assert on
what was invoked and with what arguments::

    assert len(mock.calls) == 1
    assert mock.calls[0]["node_name"] == "triage"
    assert mock.calls[0]["input"]["severity"] == "S1"
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
    ProviderError,
)


@dataclass
class _InvocationRecord:
    """A record of a single mock invocation."""

    run_id: str
    node_name: str
    idempotency_key: str
    input: Dict[str, Any]
    config: Dict[str, Any]


class MockProvider(Provider):
    """Mock / test provider (``mock``)."""

    provider_id = "mock"

    def __init__(self) -> None:
        # Canned outputs by idempotency key
        self._by_key: Dict[str, Dict[str, Any]] = {}
        # Canned outputs by node name
        self._by_node: Dict[str, Dict[str, Any]] = {}
        # Errors by node name
        self._errors_by_node: Dict[str, ProviderError] = {}
        # Global fallback output
        self._default: Optional[Dict[str, Any]] = None
        # Invocation log
        self.calls: List[_InvocationRecord] = []
        # Deploy call log
        self.deploy_calls: List[Dict[str, Any]] = []
        # Undeploy call log
        self.undeploy_calls: List[Dict[str, Any]] = []
        # Canned deploy artifacts by node name
        self._deploy_artifacts: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------
    # Registration API
    # ------------------------------------------------------------------

    def register(self, idempotency_key: str, output: Dict[str, Any]) -> None:
        """Register a canned output for a specific idempotency key.

        Args:
            idempotency_key: Exact key to match (from ``compute_idempotency_key``).
            output: The payload that ``await_result`` will return.
        """
        self._by_key[idempotency_key] = output

    def register_for_node(self, node_name: str, output: Dict[str, Any]) -> None:
        """Register a canned output for all invocations of a named node.

        Args:
            node_name: Node instance name (e.g. ``"triage"``).
            output: The payload that ``await_result`` will return.
        """
        self._by_node[node_name] = output

    def register_error(self, node_name: str, error: ProviderError) -> None:
        """Register a ``ProviderError`` to raise for all invocations of a node.

        Error registration takes precedence over output registration for the
        same node name.

        Args:
            node_name: Node instance name.
            error: The error to raise from ``await_result``.
        """
        self._errors_by_node[node_name] = error

    def set_default(self, output: Dict[str, Any]) -> None:
        """Set a fallback output returned when no other registration matches.

        Args:
            output: The payload that ``await_result`` will return.
        """
        self._default = output

    def register_deploy(self, node_name: str, artifacts: Dict[str, Any]) -> None:
        """Register canned deploy artifacts for a named node.

        Args:
            node_name: Node instance name to match on ``deploy`` calls.
            artifacts: The dict that ``deploy`` will return for this node.
        """
        self._deploy_artifacts[node_name] = artifacts

    def reset(self) -> None:
        """Clear all registrations and call records.  Useful between tests."""
        self._by_key.clear()
        self._by_node.clear()
        self._errors_by_node.clear()
        self._default = None
        self.calls.clear()
        self.deploy_calls.clear()
        self._deploy_artifacts.clear()

    # ------------------------------------------------------------------
    # Provider contract
    # ------------------------------------------------------------------

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        """Record the invocation and return a handle immediately.

        The handle's ``provider_data`` stores the resolved output (or error)
        so ``poll`` and ``await_result`` can return without additional I/O.
        """
        self.calls.append(
            _InvocationRecord(
                run_id=context.run_id,
                node_name=context.node_name,
                idempotency_key=context.idempotency_key,
                input=dict(input),
                config=dict(config),
            )
        )

        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
        )

        # Check for registered error first
        if context.node_name in self._errors_by_node:
            handle.provider_data["error"] = self._errors_by_node[context.node_name]
            handle.provider_data["status"] = ExecutionStatus.FAILED
            return handle

        # Resolve output: key → node → default → error
        output = (
            self._by_key.get(context.idempotency_key)
            or self._by_node.get(context.node_name)
            or self._default
        )
        if output is None:
            raise ProviderError(
                code="no_canned_output",
                message=(
                    f"MockProvider: no output registered for node '{context.node_name}' "
                    f"or key '{context.idempotency_key}'"
                ),
                retryable=False,
            )

        handle.provider_data["output"] = output
        handle.provider_data["status"] = ExecutionStatus.COMPLETED
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        """Return the pre-resolved status from the handle (no I/O)."""
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(
        self,
        handle: ExecutionHandle,
        timeout: Optional[float] = None,  # noqa: ARG002
    ) -> Dict[str, Any]:
        """Return the canned output or raise the registered error.

        The ``timeout`` parameter is accepted for interface compatibility but
        is not enforced — mock executions complete instantly.
        """
        status = handle.provider_data.get("status", ExecutionStatus.COMPLETED)

        if status == ExecutionStatus.FAILED:
            error: ProviderError = handle.provider_data["error"]
            raise error

        output = handle.provider_data.get("output")
        if output is None:
            raise ProviderError(
                code="missing_output",
                message="MockProvider: handle completed but output was not set",
                retryable=False,
            )
        return output

    def cancel(self, handle: ExecutionHandle) -> None:
        """Mark the handle cancelled (no-op externally)."""
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def deploy(self, node_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """Record the deploy call and return any registered canned artifacts."""
        self.deploy_calls.append({"node_name": node_name, "config": dict(config)})
        return self._deploy_artifacts.get(node_name, {})

    def undeploy(
        self,
        node_name: str,
        config: Dict[str, Any],
        artifacts: Dict[str, Any],
    ) -> None:
        """Record the undeploy call."""
        self.undeploy_calls.append({
            "node_name": node_name,
            "config": dict(config),
            "artifacts": dict(artifacts),
        })
