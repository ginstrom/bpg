from __future__ import annotations

from typing import Any, Dict

from bpg.compiler.ir import compile_process
from bpg.compiler.validator import validate_process
from bpg.providers import PROVIDER_REGISTRY
from bpg.runtime.langgraph_runtime import LangGraphRuntime


class LangGraphExecutionBackend:
    """LangGraph-backed runtime backend implementation."""

    name = "langgraph"

    def run(
        self,
        *,
        process: Any,
        state_store: Any,
        run_id: str,
        input_payload: Dict[str, Any],
        cached_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        validate_process(process)
        ir = compile_process(process)

        providers: Dict[str, Any] = {}
        for provider_id, cls in PROVIDER_REGISTRY.items():
            try:
                providers[provider_id] = cls()
            except Exception:
                # Some providers require custom constructor args.
                continue

        runtime = LangGraphRuntime(
            ir=ir,
            providers=providers,
            initial_result_cache=cached_results,
        )
        return runtime.run(input_payload=input_payload, run_id=run_id)
