"""Template builders for intent-based process scaffolding."""

from __future__ import annotations

import re
from typing import Any


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "generated-process"


def build_base_process(*, name: str, description: str | None = None) -> dict[str, Any]:
    return {
        "metadata": {
            "name": name,
            "version": "0.1.0",
            "description": description or f"Scaffold generated for process: {name}",
        },
        "types": {
            "IntentInput": {"request": "string"},
            "TaskOutput": {"result": "string"},
        },
        "node_types": {
            "intent_trigger@v1": {
                "in": "object",
                "out": "IntentInput",
                "provider": "dashboard.form",
                "version": "v1",
                "config_schema": {},
            },
            "task_step@v1": {
                "in": "IntentInput",
                "out": "TaskOutput",
                "provider": "mock",
                "version": "v1",
                "config_schema": {},
            },
        },
        "nodes": {
            "input": {"type": "intent_trigger@v1", "config": {}},
            "task": {"type": "task_step@v1", "config": {}},
        },
        "trigger": "input",
        "edges": [
            {
                "from": "input",
                "to": "task",
                "with": {"request": "trigger.in.request"},
            }
        ],
        "output": "task.out",
    }
