"""Core BPG providers for internal orchestration and control flow.

Includes:
- PassthroughProvider: Returns input payload as output. Used for modules.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
)


class PassthroughProvider(Provider):
    """Passthrough provider (``core.passthrough``).

    Returns exactly what it receives.  Used by the BPG compiler for synthetic
    module boundary nodes.
    """

    provider_id = "core.passthrough"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        """Return a handle that points directly to the input payload."""
        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
        )
        handle.provider_data["output"] = dict(input)
        handle.provider_data["status"] = ExecutionStatus.COMPLETED
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        """Passthrough nodes are always complete immediately."""
        return ExecutionStatus.COMPLETED

    def await_result(
        self,
        handle: ExecutionHandle,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Return the output payload stored in the handle."""
        return handle.provider_data["output"]

    def cancel(self, handle: ExecutionHandle) -> None:
        """No-op for passthrough."""
        pass

    def deploy(self, node_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        """No-op for passthrough."""
        return {}
