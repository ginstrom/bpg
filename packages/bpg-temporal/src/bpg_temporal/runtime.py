from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Dict
import uuid

from bpg_langgraph import (
    CheckpointBlobStore,
    CheckpointPolicy,
    InMemoryCheckpointBlobStore,
    LangGraphBehavior,
    LangGraphNodeCheckpoint,
    LangGraphNodeMetadata,
    LangGraphNodeRunResult,
)
from bpg.compiler.ir import compile_process
from bpg.compiler.validator import validate_process
from bpg.providers import PROVIDER_REGISTRY
from bpg.runtime.langgraph_runtime import LangGraphRuntime
from bpg.runtime.observability import build_runtime_event_sink
from bpg_temporal.metadata import (
    TemporalMetadata,
    enrich_run_event_with_temporal_metadata,
    extract_temporal_metadata,
    extract_trace_context,
    trace_context_carrier_from_payload,
)


class LangGraphNodeWorkflow:
    """Temporal-owned child workflow contract for a LangGraph-backed node."""

    def __init__(
        self,
        *,
        behavior: LangGraphBehavior,
        metadata: LangGraphNodeMetadata,
        blob_store: InMemoryCheckpointBlobStore | None = None,
    ) -> None:
        self._behavior = behavior
        self._metadata = metadata
        self._blob_store = blob_store or InMemoryCheckpointBlobStore()
        self._checkpoints: dict[str, LangGraphNodeCheckpoint] = {}

    def run(
        self,
        *,
        input_payload: Dict[str, Any],
        run_id: str,
        max_steps: int | None = None,
    ) -> LangGraphNodeRunResult:
        return self._drive(
            state=dict(input_payload),
            run_id=run_id,
            next_step_index=0,
            max_steps=max_steps,
        )

    def resume(
        self,
        *,
        run_id: str,
        checkpoint_id: str,
        max_steps: int | None = None,
    ) -> LangGraphNodeRunResult:
        checkpoint = self._checkpoints[checkpoint_id]
        if checkpoint.run_id != run_id:
            raise ValueError(
                f"Checkpoint {checkpoint_id!r} belongs to run {checkpoint.run_id!r}, not {run_id!r}"
            )
        state = self._materialize_state(checkpoint)
        return self._drive(
            state=state,
            run_id=run_id,
            next_step_index=checkpoint.step_index,
            max_steps=max_steps,
        )

    def _drive(
        self,
        *,
        state: Dict[str, Any],
        run_id: str,
        next_step_index: int,
        max_steps: int | None,
    ) -> LangGraphNodeRunResult:
        executed_steps = 0
        current_state = dict(state)

        while True:
            step_result = self._behavior.step(
                state=current_state,
                metadata=self._metadata,
                run_id=run_id,
                step_index=next_step_index,
            )
            current_state = dict(step_result.state)
            next_step_index += 1
            executed_steps += 1

            if step_result.completed:
                return LangGraphNodeRunResult(
                    completed=True,
                    state=current_state,
                    output=step_result.output,
                )

            if max_steps is not None and executed_steps >= max_steps:
                checkpoint = self._save_checkpoint(
                    run_id=run_id,
                    step_index=next_step_index,
                    state=current_state,
                )
                return LangGraphNodeRunResult(
                    completed=False,
                    state=current_state,
                    checkpoint=checkpoint,
                )

    def _save_checkpoint(
        self,
        *,
        run_id: str,
        step_index: int,
        state: Dict[str, Any],
    ) -> LangGraphNodeCheckpoint:
        checkpoint_id = f"lgcp-{uuid.uuid4()}"
        encoded = json.dumps(state, sort_keys=True, separators=(",", ":")).encode("utf-8")
        policy = self._metadata.checkpoint

        if policy.spill_to_blob and len(encoded) > policy.max_inline_bytes:
            blob_key = self._blob_store.put_json(state)
            checkpoint = LangGraphNodeCheckpoint(
                checkpoint_id=checkpoint_id,
                run_id=run_id,
                step_index=step_index,
                blob_key=blob_key,
            )
        else:
            checkpoint = LangGraphNodeCheckpoint(
                checkpoint_id=checkpoint_id,
                run_id=run_id,
                step_index=step_index,
                state=dict(state),
            )
        self._checkpoints[checkpoint_id] = checkpoint
        return checkpoint

    def _materialize_state(self, checkpoint: LangGraphNodeCheckpoint) -> Dict[str, Any]:
        if checkpoint.state is not None:
            return dict(checkpoint.state)
        if checkpoint.blob_key is None:
            raise ValueError(f"Checkpoint {checkpoint.checkpoint_id!r} has no stored state")
        return self._blob_store.get_json(checkpoint.blob_key)


@dataclass(slots=True)
class BpgWorkflow:
    """Minimal workflow wrapper for the Temporal-owned execution path."""

    process: Any
    providers: Dict[str, Any]
    cached_results: Dict[str, Dict[str, Any]]
    temporal_metadata: TemporalMetadata

    def run(self, *, input_payload: Dict[str, Any], run_id: str) -> Dict[str, Any]:
        validate_process(self.process)
        ir = compile_process(self.process)
        trace_parent_context = extract_trace_context(
            trace_context_carrier_from_payload(input_payload)
        )
        runtime = LangGraphRuntime(
            ir=ir,
            providers=self.providers,
            initial_result_cache=self.cached_results,
            event_sink=build_runtime_event_sink(
                self.process,
                trace_parent_context=trace_parent_context,
            ),
        )
        result = runtime.run(input_payload=input_payload, run_id=run_id)
        metadata = (
            self.temporal_metadata
            if self.temporal_metadata.workflow_id
            else extract_temporal_metadata(
                namespace=self.temporal_metadata.namespace or "default",
                workflow_id=run_id,
                run_id=self.temporal_metadata.run_id,
                activity_id=self.temporal_metadata.activity_id,
                activity_type=self.temporal_metadata.activity_type,
                attempt=self.temporal_metadata.attempt,
                task_queue=self.temporal_metadata.task_queue,
            )
        )
        result["temporal"] = metadata.to_result_metadata()
        result["execution_log"] = [
            enrich_run_event_with_temporal_metadata(entry, metadata)
            for entry in result.get("execution_log", [])
        ]
        return result


class TemporalRuntime:
    """Bootstrap layer for the Temporal-owned runtime surface.

    This keeps the public execution entrypoint under ``bpg-temporal`` even
    while the repo still uses the legacy orchestrator implementation beneath it.
    """

    backend_name = "temporal"

    def build_langgraph_node_workflow(
        self,
        *,
        behavior: LangGraphBehavior,
        metadata: LangGraphNodeMetadata | None = None,
        blob_store: CheckpointBlobStore | None = None,
    ) -> LangGraphNodeWorkflow:
        return LangGraphNodeWorkflow(
            behavior=behavior,
            metadata=metadata or LangGraphNodeMetadata(
                engine="langgraph",
                checkpoint=CheckpointPolicy(),
            ),
            blob_store=blob_store,
        )

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

        temporal_metadata = extract_temporal_metadata()

        return BpgWorkflow(
            process=process,
            providers=providers,
            cached_results=cached_results or {},
            temporal_metadata=temporal_metadata,
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
        result.setdefault("temporal", workflow.temporal_metadata.to_result_metadata())
        return result
