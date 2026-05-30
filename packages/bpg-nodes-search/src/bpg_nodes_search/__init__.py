"""Vector search, embedding, and web search BPG nodes."""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from bpg_sdk import node
from bpg_sdk.manifest import Idempotency, ObservabilitySupport, RetrySafety, SideEffects

_PKG = "bpg.nodes.search@v1"


def _is_dry_run(payload: dict[str, Any]) -> bool:
    raw = payload.get("dry_run")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    mode = os.getenv("BPG_EXECUTION_MODE", "").strip().lower()
    if mode in {"dry-run", "dry_run"}:
        return True
    return os.getenv("BPG_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}


def _store_path(payload: dict[str, Any]) -> Path:
    if isinstance(payload.get("store_path"), str) and str(payload["store_path"]).strip():
        return Path(str(payload["store_path"]))
    store_dir = str(payload.get("store_dir") or os.getenv("BPG_SEARCH_STORE_DIR", ".bpg-state/search"))
    store_key = str(payload.get("store", "search_main"))
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]", "_", store_key)
    return Path(store_dir) / f"{safe_key}.jsonl"


def _embed_vector(text: str, dims: int = 16) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [(float(digest[i % len(digest)]) / 127.5) - 1.0 for i in range(dims)]


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    lhs, rhs = a[:size], b[:size]
    dot = sum(x * y for x, y in zip(lhs, rhs))
    mag_a = sum(x * x for x in lhs) ** 0.5
    mag_b = sum(y * y for y in rhs) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def _lexical_score(query: str, text: str) -> float:
    terms = [t for t in re.findall(r"[a-zA-Z0-9]+", query.lower()) if t]
    if not terms:
        return 0.0
    haystack = text.lower()
    return float(sum(1 for t in terms if t in haystack)) / float(len(terms))


@node(
    package=_PKG,
    node_id="embed.text",
    input_schema={
        "type": "object",
        "properties": {
            "chunks": {"type": "array"},
            "query": {"type": "string"},
            "top_k": {"type": "integer"},
        },
    },
    output_schema={"type": "object"},
    capabilities=["embedding"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def embed_text(payload: dict[str, Any]) -> dict[str, Any]:
    if isinstance(payload.get("chunks"), list):
        items: list[dict[str, Any]] = []
        for chunk in payload["chunks"]:
            if not isinstance(chunk, dict):
                continue
            text = chunk.get("text")
            if not isinstance(text, str):
                continue
            items.append(
                {
                    "source_id": str(chunk.get("source_id", "")),
                    "chunk_id": str(chunk.get("chunk_id", "")),
                    "text": text,
                    "vector": _embed_vector(text),
                    "metadata": chunk.get("metadata", {}) if isinstance(chunk.get("metadata"), dict) else {},
                }
            )
        return {"items": items}

    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("embed.text requires query string or chunks list")
    return {"query": query, "vector": _embed_vector(query), "top_k": payload.get("top_k")}


@node(
    package=_PKG,
    node_id="weaviate.upsert",
    input_schema={
        "type": "object",
        "properties": {
            "items": {"type": "array"},
            "store": {"type": "string"},
            "store_dir": {"type": "string"},
            "store_path": {"type": "string"},
        },
        "required": ["items"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "inserted": {"type": "integer"},
            "updated": {"type": "integer"},
            "failed": {"type": "integer"},
        },
    },
    capabilities=["vector_upsert"],
    side_effects=SideEffects.WRITES,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def weaviate_upsert(payload: dict[str, Any]) -> dict[str, Any]:
    items = payload.get("items")
    if not isinstance(items, list):
        raise ValueError("weaviate.upsert requires items as a list")

    store_path = _store_path(payload)
    store_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, dict[str, Any]] = {}
    if store_path.exists():
        for line in store_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            chunk_id = record.get("chunk_id")
            if isinstance(chunk_id, str) and chunk_id:
                existing[chunk_id] = record

    inserted = updated = failed = 0
    for item in items:
        if not isinstance(item, dict):
            failed += 1
            continue
        chunk_id = item.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id:
            failed += 1
            continue
        record = {
            "source_id": str(item.get("source_id", "")),
            "chunk_id": chunk_id,
            "text": str(item.get("text", "")),
            "vector": item.get("vector", []),
            "metadata": item.get("metadata", {}) if isinstance(item.get("metadata"), dict) else {},
        }
        if chunk_id in existing:
            updated += 1
        else:
            inserted += 1
        existing[chunk_id] = record

    with store_path.open("w", encoding="utf-8") as f:
        for record in existing.values():
            f.write(json.dumps(record, sort_keys=True) + "\n")

    return {"inserted": inserted, "updated": updated, "failed": failed}


@node(
    package=_PKG,
    node_id="weaviate.hybrid_search",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "vector": {"type": "array"},
            "top_k": {"type": "integer"},
            "alpha": {"type": "number"},
            "store": {"type": "string"},
        },
        "required": ["query", "vector"],
    },
    output_schema={
        "type": "object",
        "properties": {"query": {"type": "string"}, "hits": {"type": "array"}},
        "required": ["query", "hits"],
    },
    capabilities=["vector_search", "hybrid_search"],
    side_effects=SideEffects.READS,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def weaviate_hybrid_search(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("weaviate.hybrid_search requires query as a string")
    query_vec = payload.get("vector")
    if not isinstance(query_vec, list):
        raise ValueError("weaviate.hybrid_search requires vector as a list")

    top_k_raw = payload.get("top_k", 8)
    alpha_raw = payload.get("alpha", 0.5)
    try:
        top_k = max(1, int(top_k_raw))
        alpha = min(1.0, max(0.0, float(alpha_raw)))
    except (TypeError, ValueError):
        raise ValueError("weaviate.hybrid_search top_k/alpha must be numeric")

    store_path = _store_path(payload)
    records: list[dict[str, Any]] = []
    if store_path.exists():
        for line in store_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)

    scored: list[tuple[float, dict[str, Any]]] = []
    q_vec = [float(v) for v in query_vec if isinstance(v, (int, float))]
    for record in records:
        text = str(record.get("text", ""))
        lexical = _lexical_score(query, text)
        vec = record.get("vector")
        vector_score = (
            _cosine_similarity(q_vec, [float(v) for v in vec if isinstance(v, (int, float))])
            if isinstance(vec, list)
            else 0.0
        )
        hybrid = ((1.0 - alpha) * lexical) + (alpha * vector_score)
        scored.append((hybrid, record))

    scored.sort(key=lambda item: item[0], reverse=True)
    hits: list[dict[str, Any]] = [
        {
            "source_id": str(record.get("source_id", "")),
            "chunk_id": str(record.get("chunk_id", "")),
            "text": str(record.get("text", "")),
            "score": float(score),
            "metadata": record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {},
        }
        for score, record in scored[:top_k]
    ]
    return {"query": query, "hits": hits}


@node(
    package=_PKG,
    node_id="web_search",
    input_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "top_k": {"type": "integer"},
            "endpoint": {"type": "string"},
            "api_key_env": {"type": "string"},
            "dry_run": {"type": "boolean"},
        },
        "required": ["query"],
    },
    output_schema={
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "results": {"type": "array"},
            "source": {"type": "string"},
        },
    },
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.NON_IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
)
def web_search(payload: dict[str, Any]) -> dict[str, Any]:
    query = payload.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ValueError("web_search requires query as a string")

    top_k_raw = payload.get("top_k", 5)
    try:
        top_k = max(1, int(top_k_raw))
    except (TypeError, ValueError):
        raise ValueError("web_search top_k must be an integer")

    if _is_dry_run(payload):
        results = [
            {
                "title": f"Dry-run result {n} for: {query}",
                "url": f"https://example.invalid/search/{n}",
                "snippet": f"Synthetic search result {n} for query '{query}'.",
            }
            for n in range(1, top_k + 1)
        ]
        return {"query": query, "results": results, "source": "dry-run"}

    endpoint = payload.get("endpoint") or os.getenv("WEB_SEARCH_ENDPOINT")
    if not isinstance(endpoint, str) or not endpoint.strip():
        raise ValueError("web_search requires endpoint or WEB_SEARCH_ENDPOINT in live mode")

    api_key_env = str(payload.get("api_key_env", "WEB_SEARCH_API_KEY"))
    require_api_key = bool(payload.get("require_api_key", True))
    api_key = os.getenv(api_key_env)
    if require_api_key and not api_key:
        raise ValueError(f"web_search missing required env {api_key_env}")

    timeout = float(payload.get("timeout_seconds", 10))
    params = {"q": query, "k": str(top_k)}
    req_url = f"{endpoint}?{urllib.parse.urlencode(params)}"
    headers = {"Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(req_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except Exception as exc:
        raise OSError(f"web_search HTTP error: {exc}") from exc

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"web_search invalid JSON response: {exc}") from exc

    raw_results = parsed.get("results") if isinstance(parsed, dict) else parsed
    if not isinstance(raw_results, list):
        raise ValueError("web_search expected response list or {results: [...]}")
    results = [
        {
            "title": str(item.get("title", "")),
            "url": str(item.get("url", "")),
            "snippet": str(item.get("snippet", item.get("description", ""))),
        }
        for item in raw_results[:top_k]
        if isinstance(item, dict)
    ]
    return {"query": query, "results": results, "source": endpoint}


__all__ = [
    "embed_text",
    "weaviate_upsert",
    "weaviate_hybrid_search",
    "web_search",
]
