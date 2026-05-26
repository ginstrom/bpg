from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict

from bpg.compiler.ir import compile_process
from bpg.compiler.validator import validate_process
from bpg.providers import PROVIDER_REGISTRY
from bpg.runtime.langgraph_runtime import LangGraphRuntime


@dataclass(slots=True)
class BpgWorkflow:
    """Minimal workflow wrapper for the Temporal-owned execution path."""

    process: Any
    providers: Dict[str, Any]
    cached_results: Dict[str, Dict[str, Any]]

    def run(self, *, input_payload: Dict[str, Any], run_id: str) -> Dict[str, Any]:
        validate_process(self.process)
        ir = compile_process(self.process)
        runtime = LangGraphRuntime(
            ir=ir,
            providers=self.providers,
            initial_result_cache=self.cached_results,
        )
        return runtime.run(input_payload=input_payload, run_id=run_id)


class TemporalRuntime:
    """Bootstrap layer for the Temporal-owned runtime surface.

    This keeps the public execution entrypoint under ``bpg-temporal`` even
    while the repo still uses the legacy orchestrator implementation beneath it.
    """

    backend_name = "temporal"

    def build_workflow(
        self,
        *,
        process: Any,
        cached_results: Dict[str, Dict[str, Any]] | None = None,
    ) -> BpgWorkflow:
        providers: Dict[str, Any] = {}
        for provider_id, factory in PROVIDER_REGISTRY.items():
            try:
                providers[provider_id] = factory()
            except Exception:
                continue
        return BpgWorkflow(
            process=process,
            providers=providers,
            cached_results=cached_results or {},
        )

    def run_workflow(
        self,
        *,
        process: Any,
        input_payload: Dict[str, Any],
        run_id: str,
        cached_results: Dict[str, Dict[str, Any]] | None = None,
    ) -> Dict[str, Any]:
        workflow = self.build_workflow(
            process=process,
            cached_results=cached_results,
        )
        result = workflow.run(input_payload=input_payload, run_id=run_id)
        result.setdefault(
            "temporal",
            {
                "workflow": "BpgWorkflow",
                "namespace": "default",
            },
        )
        return result
