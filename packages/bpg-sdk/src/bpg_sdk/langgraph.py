from __future__ import annotations

from typing import Any


def build_langgraph_registration(
    *,
    tool_registry: list[str] | None = None,
    structured_output_schema: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a normalized LangGraph registration payload for SDK-authored nodes."""

    return {
        "engine": "langgraph",
        "tool_registry": list(tool_registry or []),
        "structured_output_schema": structured_output_schema,
    }
