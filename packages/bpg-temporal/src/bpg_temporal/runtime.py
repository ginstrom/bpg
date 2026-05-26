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
        provider_init_failures: Dict[str, Exception] = {}
        required_provider_ids = {
            node_type.provider
            for node_type in process.node_types.values()
        }
        for provider_id, factory in PROVIDER_REGISTRY.items():
            try:
                providers[provider_id] = factory()
            except Exception as exc:
                provider_init_failures[provider_id] = exc

        required_failures = {
            provider_id: exc
            for provider_id, exc in provider_init_failures.items()
            if provider_id in required_provider_ids
        }
        if required_failures:
            details = ", ".join(
                f"{provider_id}: {type(exc).__name__}: {exc}"
                for provider_id, exc in sorted(required_failures.items())
            )
            first_error = next(iter(required_failures.values()))
            raise RuntimeError(
                "Failed to initialize provider(s) required by the process: "
                f"{details}"
            ) from first_error

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
        # Stub: real Temporal metadata (workflow ID, namespace) will be populated
        # when the actual Temporal client is wired up in step 4.
        result.setdefault(
            "temporal",
            {
                "workflow": "BpgWorkflow",
                "namespace": "default",
            },
        )
        return result
