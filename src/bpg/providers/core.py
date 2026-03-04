"""Core BPG providers for internal orchestration and control flow.

Includes:
- PassthroughProvider: Returns input payload as output. Used for modules.
- DatasetSelectProvider: Selects rows from an inline dataset by row IDs.
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


class DatasetSelectProvider(Provider):
    """Dataset row selector (``core.dataset.select_rows``).

    Config:
      - rows: list<object> (required), each row should include ``row_id``.
      - row_id_field: string (optional, default: ``row_id``)

    Input:
      - ``row_ids``: list<number|string>

    Output:
      - ``rows``: list<object> filtered in the same order as ``row_ids``.
    """

    provider_id = "core.dataset.select_rows"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        row_id_field = str(config.get("row_id_field") or "row_id")
        raw_rows = config.get("rows")
        if not isinstance(raw_rows, list):
            raise ValueError("core.dataset.select_rows requires config.rows as a list")
        row_ids = input.get("row_ids", [])
        if not isinstance(row_ids, list):
            raise ValueError("core.dataset.select_rows expects input.row_ids as a list")

        index: dict[str, Dict[str, Any]] = {}
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            key = row.get(row_id_field)
            if key is None:
                continue
            index[str(key)] = dict(row)

        selected: list[Dict[str, Any]] = []
        for raw_id in row_ids:
            key = str(int(raw_id)) if isinstance(raw_id, (int, float)) else str(raw_id)
            row = index.get(key)
            if row is not None:
                selected.append(row)

        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
        )
        handle.provider_data["output"] = {"rows": selected}
        handle.provider_data["status"] = ExecutionStatus.COMPLETED
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return ExecutionStatus.COMPLETED

    def await_result(
        self,
        handle: ExecutionHandle,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        return handle.provider_data["output"]

    def cancel(self, handle: ExecutionHandle) -> None:
        pass

    def deploy(self, node_name: str, config: Dict[str, Any]) -> Dict[str, Any]:
        return {}
