"""Canonical normalization helpers for deterministic process specs."""

from __future__ import annotations

import json
from typing import Any

from bpg.models.schema import Process


def _sort_mapping(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _sort_mapping(value[k]) for k in sorted(value, key=lambda item: str(item))}
    if isinstance(value, list):
        return [_sort_mapping(item) for item in value]
    return value


def normalize_process_dict(raw_process: dict[str, Any]) -> dict[str, Any]:
    """Return a canonical dictionary representation of a process spec."""
    normalized = dict(raw_process)
    for section in ("types", "node_types", "modules", "nodes"):
        content = normalized.get(section) or {}
        if isinstance(content, dict):
            normalized[section] = {k: content[k] for k in sorted(content)}

    edges = normalized.get("edges") or []
    if isinstance(edges, list):
        canon_edges: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            edge_copy = dict(edge)
            if isinstance(edge_copy.get("with"), dict):
                edge_copy["with"] = {k: edge_copy["with"][k] for k in sorted(edge_copy["with"])}
            canon_edges.append(edge_copy)
        normalized["edges"] = sorted(
            canon_edges,
            key=lambda edge: (
                edge.get("from", ""),
                edge.get("to", ""),
                edge.get("when", "") or "",
                json.dumps(edge.get("with", {}) or {}, sort_keys=True),
            ),
        )
    return _sort_mapping(normalized)


def normalize_process(process: Process) -> Process:
    """Normalize a Process model into canonical ordering/shape."""
    raw = process.model_dump(by_alias=True, exclude_none=True)
    normalized_raw = normalize_process_dict(raw)
    return Process.model_validate(normalized_raw)
