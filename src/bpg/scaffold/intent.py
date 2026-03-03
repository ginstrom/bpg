"""Intent-to-spec scaffold generation."""

from __future__ import annotations

from typing import Any

from bpg.scaffold.templates import build_base_process


def scaffold_from_intent(intent: str) -> tuple[dict[str, Any], dict[str, Any]]:
    process = build_base_process(intent)
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

    lowered = intent.lower()
    if "review" in lowered or "approve" in lowered:
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
