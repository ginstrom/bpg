from __future__ import annotations

from pathlib import Path

from bpg.compiler.parser import parse_process_file
from bpg_langgraph import (
    CheckpointPolicy,
    InMemoryCheckpointBlobStore,
    LangGraphNodeMetadata,
    LangGraphStepResult,
)
from bpg_temporal.runtime import LangGraphNodeWorkflow


class _TwoStepBehavior:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def step(self, *, state, metadata, run_id, step_index):
        _ = metadata
        _ = run_id
        current_step = state.get("step", 0)
        if current_step == 0:
            self.calls.append(f"model:{step_index}")
            return LangGraphStepResult(
                state={"step": 1, "draft": "ready"},
                completed=False,
            )
        self.calls.append(f"tool:{step_index}")
        return LangGraphStepResult(
            state={"step": 2, "draft": state["draft"]},
            output={"answer": "done"},
            completed=True,
        )


class _LargeStateBehavior:
    def step(self, *, state, metadata, run_id, step_index):
        _ = state
        _ = metadata
        _ = run_id
        _ = step_index
        return LangGraphStepResult(
            state={"step": 1, "transcript": "x" * 512},
            completed=False,
        )


def test_langgraph_node_workflow_resumes_from_checkpoint_without_replaying_steps():
    behavior = _TwoStepBehavior()
    workflow = LangGraphNodeWorkflow(
        behavior=behavior,
        metadata=LangGraphNodeMetadata(
            engine="langgraph",
            checkpoint=CheckpointPolicy(max_inline_bytes=1024),
            tool_registry=["search.docs"],
            structured_output_schema={"answer": "string"},
        ),
    )

    partial = workflow.run(
        input_payload={"prompt": "hello"},
        run_id="run-1",
        max_steps=1,
    )

    assert partial.completed is False
    assert partial.checkpoint is not None
    assert behavior.calls == ["model:0"]

    resumed = workflow.resume(
        run_id="run-1",
        checkpoint_id=partial.checkpoint.checkpoint_id,
    )

    assert resumed.completed is True
    assert resumed.output == {"answer": "done"}
    assert behavior.calls == ["model:0", "tool:1"]


def test_langgraph_node_workflow_spills_large_checkpoint_state_to_blob_store():
    blob_store = InMemoryCheckpointBlobStore()
    workflow = LangGraphNodeWorkflow(
        behavior=_LargeStateBehavior(),
        metadata=LangGraphNodeMetadata(
            engine="langgraph",
            checkpoint=CheckpointPolicy(max_inline_bytes=64),
        ),
        blob_store=blob_store,
    )

    partial = workflow.run(
        input_payload={"prompt": "hello"},
        run_id="run-blob",
        max_steps=1,
    )

    assert partial.completed is False
    assert partial.checkpoint is not None
    assert partial.checkpoint.blob_key is not None
    assert partial.checkpoint.state is None
    assert blob_store.get_json(partial.checkpoint.blob_key)["transcript"] == "x" * 512


def test_parse_process_file_preserves_langgraph_node_type_metadata(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
types:
  In:
    prompt: string
  Out:
    answer: string
node_types:
  ai_agent@v1:
    in: In
    out: Out
    provider: mock
    version: v1
    config_schema: {}
    engine: langgraph
    checkpoint:
      max_inline_bytes: 256
    tool_registry:
      - search.docs
      - calc
    structured_output_schema:
      answer: string
nodes:
  start:
    type: ai_agent@v1
    config: {}
trigger: start
edges: []
""",
        encoding="utf-8",
    )

    process = parse_process_file(process_file)
    node_type = process.node_types["ai_agent@v1"]

    assert node_type.engine == "langgraph"
    assert node_type.checkpoint is not None
    assert node_type.checkpoint.max_inline_bytes == 256
    assert node_type.tool_registry == ["search.docs", "calc"]
    assert node_type.structured_output_schema == {"answer": "string"}
