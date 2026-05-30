"""Human-in-the-loop and agent pipeline BPG nodes."""

from __future__ import annotations

from typing import Any

from bpg_sdk import node
from bpg_sdk.manifest import Idempotency, ObservabilitySupport, RetrySafety, SideEffects

_PKG = "bpg.nodes.human@v1"


@node(
    package=_PKG,
    node_id="dashboard.form",
    input_schema={"type": "object"},
    output_schema={"type": "object"},
    capabilities=["human-in-the-loop"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
    observability=ObservabilitySupport.REQUIRED,
)
def dashboard_form(payload: dict[str, Any]) -> dict[str, Any]:
    defaults = payload.get("defaults", {})
    if defaults is not None and not isinstance(defaults, dict):
        raise ValueError("dashboard.form expects defaults to be an object")
    output = dict(defaults or {})
    # Merge all non-config keys from payload as the "input"
    for key, value in payload.items():
        if key != "defaults":
            output[key] = value
    return output


@node(
    package=_PKG,
    node_id="agent.pipeline",
    input_schema={"type": "object"},
    output_schema={
        "type": "object",
        "properties": {
            "risk": {"type": "string"},
            "summary": {"type": "string"},
            "labels": {"type": "array"},
        },
    },
    capabilities=["agent"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
)
def agent_pipeline(payload: dict[str, Any]) -> dict[str, Any]:
    mock_output = payload.get("mock_output")
    if mock_output is not None:
        if not isinstance(mock_output, dict):
            raise ValueError("agent.pipeline expects mock_output to be an object")
        return dict(mock_output)

    severity = str(payload.get("severity", "")).upper()
    risk = "high" if severity in {"S1", "P0"} else "med" if severity in {"S2", "P1"} else "low"
    title = str(payload.get("title", "")).strip() or "No title"
    return {
        "risk": risk,
        "summary": title,
        "labels": list(payload.get("labels", [])) if isinstance(payload.get("labels"), list) else [],
    }


__all__ = [
    "dashboard_form",
    "agent_pipeline",
]
