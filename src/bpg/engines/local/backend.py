from __future__ import annotations

from typing import Any, Dict

from bpg.compiler.ir import compile_process
from bpg.compiler.validator import validate_process
from bpg.providers import PROVIDER_REGISTRY
from bpg.runtime.orchestrator import BpgOrchestrator, ProviderNodeExecutionAdapter


class LocalExecutionBackend:
    """Local backend used to prove backend pluggability.

    This backend intentionally shares the same execution semantics path as the
    LangGraph backend for now, while exposing a distinct backend identity and
    selection path (`--engine local`).
    """

    name = "local"

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
        _ = cached_results
        validate_process(process)
        ir = compile_process(process)

        providers: Dict[str, Any] = {}
        for provider_id, cls in PROVIDER_REGISTRY.items():
            try:
                providers[provider_id] = cls()
            except Exception:
                continue

        adapter = ProviderNodeExecutionAdapter(providers)
        orchestrator = BpgOrchestrator(ir=ir, node_adapter=adapter)
        return orchestrator.run(input_payload=input_payload, run_id=run_id)
