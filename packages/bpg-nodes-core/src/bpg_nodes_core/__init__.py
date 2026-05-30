"""Core data-manipulation and control-flow BPG nodes."""

from __future__ import annotations

import csv as _csv
import hashlib
import os
import re
import time
from pathlib import Path
from typing import Any

from bpg_sdk import node
from bpg_sdk.manifest import Idempotency, ObservabilitySupport, RetrySafety, SideEffects

_PKG = "bpg.nodes.core@v1"

_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")


@node(
    package=_PKG,
    node_id="passthrough",
    input_schema={"type": "object"},
    output_schema={"type": "object"},
    capabilities=["control_flow"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def passthrough(payload: dict[str, Any]) -> dict[str, Any]:
    return dict(payload)


@node(
    package=_PKG,
    node_id="dataset.select_rows",
    input_schema={
        "type": "object",
        "properties": {
            "rows": {"type": "array"},
            "row_ids": {"type": "array"},
            "row_id_field": {"type": "string"},
        },
        "required": ["rows"],
    },
    output_schema={"type": "object", "properties": {"rows": {"type": "array"}}, "required": ["rows"]},
    capabilities=["data_io"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def dataset_select_rows(payload: dict[str, Any]) -> dict[str, Any]:
    row_id_field = str(payload.get("row_id_field") or "row_id")
    raw_rows = payload.get("rows")
    if not isinstance(raw_rows, list):
        raise ValueError("dataset.select_rows requires rows as a list")
    row_ids = payload.get("row_ids")
    if row_ids is None:
        return {"rows": list(raw_rows)}
    if not isinstance(row_ids, list):
        raise ValueError("dataset.select_rows expects row_ids as a list")

    index: dict[str, dict[str, Any]] = {}
    for row in raw_rows:
        if not isinstance(row, dict):
            continue
        key = row.get(row_id_field)
        if key is None:
            continue
        index[str(key)] = dict(row)

    selected: list[dict[str, Any]] = []
    for raw_id in row_ids:
        key = str(int(raw_id)) if isinstance(raw_id, (int, float)) else str(raw_id)
        row = index.get(key)
        if row is not None:
            selected.append(row)
    return {"rows": selected}


@node(
    package=_PKG,
    node_id="csv.read",
    input_schema={
        "type": "object",
        "properties": {
            "path": {"type": "string"},
            "row_ids": {"type": "array"},
            "row_id_field": {"type": "string"},
            "review_column": {"type": "string"},
            "sentiment_column": {"type": "string"},
            "output_review_field": {"type": "string"},
            "output_sentiment_field": {"type": "string"},
        },
        "required": ["path"],
    },
    output_schema={"type": "object", "properties": {"rows": {"type": "array"}}, "required": ["rows"]},
    capabilities=["data_io", "file_io"],
    side_effects=SideEffects.READS,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def csv_read(payload: dict[str, Any]) -> dict[str, Any]:
    csv_path = payload.get("path")
    if not isinstance(csv_path, str) or not csv_path.strip():
        raise ValueError("csv.read requires path as a non-empty string")

    row_id_field = str(payload.get("row_id_field") or "row_id")
    review_column = str(payload.get("review_column") or "review")
    sentiment_column = str(payload.get("sentiment_column") or "sentiment")
    output_review_field = str(payload.get("output_review_field") or "review")
    output_sentiment_field = str(payload.get("output_sentiment_field") or "source_sentiment")

    row_ids = payload.get("row_ids")
    if row_ids is not None and not isinstance(row_ids, list):
        raise ValueError("csv.read expects row_ids as a list when provided")

    path = Path(csv_path)
    if not path.exists():
        raise ValueError(f"csv.read could not find CSV at: {csv_path}")

    rows: list[dict[str, Any]] = []
    with path.open(newline="", encoding="utf-8") as f:
        reader = _csv.DictReader(f)
        for idx, row in enumerate(reader, start=1):
            out_row: dict[str, Any] = {
                row_id_field: idx,
                output_review_field: row.get(review_column, ""),
                output_sentiment_field: row.get(sentiment_column, ""),
            }
            rows.append(out_row)

    if row_ids is not None:
        index = {str(r[row_id_field]): r for r in rows}
        selected: list[dict[str, Any]] = []
        for raw_id in row_ids:
            key = str(int(raw_id)) if isinstance(raw_id, (int, float)) else str(raw_id)
            row = index.get(key)
            if row is not None:
                selected.append(row)
        rows = selected

    return {"rows": rows}


@node(
    package=_PKG,
    node_id="flow.loop",
    input_schema={
        "type": "object",
        "properties": {"items": {"type": "array"}, "max_iterations": {"type": "integer"}},
        "required": ["items"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "items": {"type": "array"},
            "count": {"type": "integer"},
            "truncated": {"type": "boolean"},
        },
    },
    capabilities=["control_flow"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def flow_loop(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError("flow.loop expects items as a list")
    max_iterations = payload.get("max_iterations", len(items))
    try:
        bound = max(0, int(max_iterations))
    except (TypeError, ValueError):
        raise ValueError("flow.loop max_iterations must be an integer")
    bounded = items[:bound]
    return {"items": bounded, "count": len(bounded), "truncated": len(items) > len(bounded)}


@node(
    package=_PKG,
    node_id="flow.fanout",
    input_schema={"type": "object", "properties": {"items": {"type": "array"}}, "required": ["items"]},
    output_schema={
        "type": "object",
        "properties": {"branches": {"type": "array"}, "count": {"type": "integer"}},
    },
    capabilities=["control_flow"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def flow_fanout(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items", [])
    if not isinstance(items, list):
        raise ValueError("flow.fanout expects items as a list")
    branches = [{"index": i, "item": item} for i, item in enumerate(items)]
    return {"branches": branches, "count": len(branches)}


@node(
    package=_PKG,
    node_id="flow.await_all",
    input_schema={"type": "object", "properties": {"results": {"type": "array"}}, "required": ["results"]},
    output_schema={
        "type": "object",
        "properties": {"results": {"type": "array"}, "count": {"type": "integer"}},
    },
    capabilities=["control_flow"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def flow_await_all(payload: dict[str, Any]) -> dict[str, Any]:
    results = payload.get("results", [])
    if not isinstance(results, list):
        raise ValueError("flow.await_all expects results as a list")
    return {"results": results, "count": len(results)}


@node(
    package=_PKG,
    node_id="timer.delay",
    input_schema={
        "type": "object",
        "properties": {"duration": {"type": "number"}, "duration_seconds": {"type": "number"}},
    },
    output_schema={
        "type": "object",
        "properties": {"ok": {"type": "boolean"}, "slept_seconds": {"type": "number"}},
    },
    capabilities=["control_flow"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def timer_delay(payload: dict[str, Any]) -> dict[str, Any]:
    duration_raw = payload.get("duration", payload.get("duration_seconds", 0))
    try:
        duration_s = float(duration_raw)
    except (TypeError, ValueError):
        raise ValueError("timer.delay requires numeric duration")
    if duration_s < 0:
        raise ValueError("timer.delay duration must be >= 0")
    if duration_s > 0:
        time.sleep(duration_s)
    return {"ok": True, "slept_seconds": duration_s}


@node(
    package=_PKG,
    node_id="process_call",
    input_schema={
        "type": "object",
        "properties": {"process_name": {"type": "string"}, "input": {"type": "object"}},
        "required": ["process_name"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "child_process": {"type": "string"},
            "child_run_id": {"type": "string"},
            "status": {"type": "string"},
        },
    },
    capabilities=["orchestration"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
    observability=ObservabilitySupport.REQUIRED,
)
def process_call(payload: dict[str, Any]) -> dict[str, Any]:
    # In the v2 Temporal system, sub-process dispatch is handled at the workflow
    # orchestration layer. This node records the dispatch intent.
    process_name = str(payload.get("process_name", ""))
    if not process_name:
        raise ValueError("process_call requires process_name")
    return {
        "child_process": process_name,
        "child_run_id": "pending",
        "status": "dispatched",
        "output": payload.get("input"),
    }


@node(
    package=_PKG,
    node_id="fs.markdown_list",
    input_schema={
        "type": "object",
        "properties": {
            "root_dir": {"type": "string"},
            "glob": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "properties": {"documents": {"type": "array"}},
        "required": ["documents"],
    },
    capabilities=["file_io"],
    side_effects=SideEffects.READS,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def fs_markdown_list(payload: dict[str, Any]) -> dict[str, Any]:
    root_dir_raw = payload.get("root_dir") or os.getenv("BPG_MARKDOWN_ROOT") or "."
    if not isinstance(root_dir_raw, str) or not root_dir_raw.strip():
        raise ValueError("fs.markdown_list requires root_dir")
    root_dir = Path(root_dir_raw).expanduser().resolve()
    if not root_dir.exists() or not root_dir.is_dir():
        raise ValueError(f"fs.markdown_list root_dir not found: {root_dir}")

    glob_pattern = payload.get("glob") or "**/*.md"
    if not isinstance(glob_pattern, str) or not glob_pattern.strip():
        raise ValueError("fs.markdown_list glob must be a non-empty string")

    documents: list[dict[str, Any]] = []
    for path in sorted(root_dir.glob(glob_pattern)):
        if not path.is_file():
            continue
        try:
            markdown = path.read_text(encoding="utf-8")
        except Exception as exc:
            raise OSError(f"failed to read markdown file {path}: {exc}") from exc
        rel_path = str(path.relative_to(root_dir))
        source_id = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:16]
        documents.append(
            {
                "source_id": source_id,
                "path": rel_path,
                "markdown": markdown,
                "metadata": {"bytes": path.stat().st_size},
            }
        )
    return {"documents": documents}


@node(
    package=_PKG,
    node_id="text.markdown_chunk",
    input_schema={
        "type": "object",
        "properties": {
            "documents": {"type": "array"},
            "chunk_size": {"type": "integer"},
            "overlap": {"type": "integer"},
        },
        "required": ["documents"],
    },
    output_schema={
        "type": "object",
        "properties": {"chunks": {"type": "array"}},
        "required": ["chunks"],
    },
    capabilities=["text_processing"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def text_markdown_chunk(payload: dict[str, Any]) -> dict[str, Any]:
    docs = payload.get("documents")
    if not isinstance(docs, list):
        raise ValueError("text.markdown_chunk requires documents as a list")

    try:
        chunk_size = int(payload.get("chunk_size", 1200))
        overlap = int(payload.get("overlap", 200))
    except (TypeError, ValueError):
        raise ValueError("text.markdown_chunk chunk_size and overlap must be integers")
    if chunk_size <= 0:
        raise ValueError("text.markdown_chunk chunk_size must be > 0")
    if overlap < 0 or overlap >= chunk_size:
        raise ValueError("text.markdown_chunk overlap must be >= 0 and < chunk_size")

    chunks: list[dict[str, Any]] = []
    stride = max(1, chunk_size - overlap)
    for doc in docs:
        if not isinstance(doc, dict):
            continue
        source_id = str(doc.get("source_id", ""))
        path = str(doc.get("path", ""))
        markdown = doc.get("markdown")
        if not isinstance(markdown, str):
            continue
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}
        for start in range(0, max(len(markdown), 1), stride):
            text = markdown[start : start + chunk_size]
            if not text:
                continue
            ordinal = len(chunks)
            chunks.append(
                {
                    "source_id": source_id,
                    "chunk_id": f"{source_id}:{ordinal}",
                    "text": text,
                    "path": path,
                    "ordinal": float(ordinal),
                    "metadata": metadata,
                }
            )
            if start + chunk_size >= len(markdown):
                break

    return {"chunks": chunks}


@node(
    package=_PKG,
    node_id="text.parse_numbers",
    input_schema={
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
    },
    output_schema={
        "type": "object",
        "properties": {"numbers": {"type": "array", "items": {"type": "number"}}},
        "required": ["numbers"],
    },
    capabilities=["text_processing"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def text_parse_numbers(payload: dict[str, Any]) -> dict[str, Any]:
    text = payload.get("text")
    if not isinstance(text, str):
        raise ValueError("text.parse_numbers requires text as a string")
    numbers = [float(token) for token in _NUMBER_RE.findall(text)]
    return {"numbers": numbers}


@node(
    package=_PKG,
    node_id="math.sum_numbers",
    input_schema={
        "type": "object",
        "properties": {"numbers": {"type": "array", "items": {"type": "number"}}},
        "required": ["numbers"],
    },
    output_schema={
        "type": "object",
        "properties": {"sum": {"type": "number"}, "count": {"type": "integer"}},
        "required": ["sum", "count"],
    },
    capabilities=["math"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def math_sum_numbers(payload: dict[str, Any]) -> dict[str, Any]:
    numbers = payload.get("numbers")
    if not isinstance(numbers, list):
        raise ValueError("math.sum_numbers requires numbers as a list")
    for idx, value in enumerate(numbers):
        if not isinstance(value, (int, float)):
            raise ValueError(f"math.sum_numbers numbers[{idx}] must be numeric")
    return {"sum": float(sum(numbers)), "count": len(numbers)}


__all__ = [
    "passthrough",
    "dataset_select_rows",
    "csv_read",
    "flow_loop",
    "flow_fanout",
    "flow_await_all",
    "timer_delay",
    "process_call",
    "fs_markdown_list",
    "text_markdown_chunk",
    "text_parse_numbers",
    "math_sum_numbers",
]
