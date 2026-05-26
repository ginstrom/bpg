from __future__ import annotations

from typing import Any, Dict

from bpg_temporal.runtime import TemporalRuntime


class TemporalExecutionBackend:
    """Single supported framework execution backend."""

    name = "temporal"

    def __init__(self, runtime: TemporalRuntime | None = None) -> None:
        self._runtime = runtime or TemporalRuntime()

    def run(
        self,
        *,
        process: Any,
        state_store: Any,
        run_id: str,
        input_payload: Dict[str, Any],
        cached_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        _ = state_store
        return self._runtime.run_workflow(
            process=process,
            input_payload=input_payload,
            run_id=run_id,
            cached_results=cached_results,
        )
