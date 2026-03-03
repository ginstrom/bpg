"""Intent-to-spec scaffold generation."""

from __future__ import annotations

from typing import Any

from bpg.scaffold.templates import build_base_process, slugify


def scaffold_process(
    *,
    name: str | None,
    description: str | None,
    with_review: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    process_name = slugify(name or "generated-process")[:48]
    process = build_base_process(name=process_name, description=description)
    todos: list[dict[str, Any]] = [
        {
            "id": "T_PROVIDER_SELECT",
            "node": "task",
            "hint": "Choose provider for task execution",
        },
        {
            "id": "T_MAPPING",
            "edge": "input->task",
            "hint": "Validate mapping from trigger input to task request",
        },
    ]

    if with_review:
        process["types"]["ReviewOut"] = {"approved": "bool", "result": "string"}
        process["node_types"]["review_step@v1"] = {
            "in": "TaskOutput",
            "out": "ReviewOut",
            "provider": "dashboard.form",
            "version": "v1",
            "config_schema": {},
        }
        process["nodes"]["review"] = {"type": "review_step@v1", "config": {}}
        process["edges"].append(
            {"from": "task", "to": "review", "with": {"result": "task.out.result"}}
        )
        process["output"] = "review.out"
        todos.append(
            {
                "id": "T_HITL_POLICY",
                "node": "review",
                "hint": "Set timeout/on_timeout and escalation policy for review step",
            }
        )

    return process, {"todos": todos}
