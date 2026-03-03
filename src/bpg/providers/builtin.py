"""Built-in providers for common BPG node types.

These are pragmatic baseline implementations that are deterministic and
self-contained, so processes can run locally without custom integrations.
"""

from __future__ import annotations

import json
import hashlib
import os
from pathlib import Path
import re
import smtplib
import time
import urllib.parse
import urllib.request
from email.message import EmailMessage
from typing import Any, Dict, Optional

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
    ProviderError,
)


def _is_dry_run(config: Dict[str, Any]) -> bool:
    raw = config.get("dry_run")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    mode = os.getenv("BPG_EXECUTION_MODE", "").strip().lower()
    if mode in {"dry-run", "dry_run"}:
        return True
    return os.getenv("BPG_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}


def _search_store_path(config: Dict[str, Any]) -> Path:
    """Resolve the local JSONL store path used by search providers."""
    if isinstance(config.get("store_path"), str) and str(config["store_path"]).strip():
        return Path(str(config["store_path"]))
    store_dir = str(config.get("store_dir") or os.getenv("BPG_SEARCH_STORE_DIR", ".bpg-state/search"))
    store_key = str(config.get("store", "search_main"))
    safe_key = re.sub(r"[^a-zA-Z0-9_.-]", "_", store_key)
    return Path(store_dir) / f"{safe_key}.jsonl"


def _embed_vector(text: str, dims: int = 16) -> list[float]:
    """Return a deterministic pseudo-embedding for text."""
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    values: list[float] = []
    for idx in range(dims):
        byte = digest[idx % len(digest)]
        # Scale to [-1, 1]
        values.append((float(byte) / 127.5) - 1.0)
    return values


def _cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    size = min(len(a), len(b))
    lhs = a[:size]
    rhs = b[:size]
    dot = sum(x * y for x, y in zip(lhs, rhs))
    mag_a = sum(x * x for x in lhs) ** 0.5
    mag_b = sum(y * y for y in rhs) ** 0.5
    if mag_a == 0.0 or mag_b == 0.0:
        return 0.0
    return dot / (mag_a * mag_b)


def _lexical_score(query: str, text: str) -> float:
    query_terms = [token for token in re.findall(r"[a-zA-Z0-9]+", query.lower()) if token]
    if not query_terms:
        return 0.0
    haystack = text.lower()
    matched = sum(1 for token in query_terms if token in haystack)
    return float(matched) / float(len(query_terms))


class AgentPipelineProvider(Provider):
    """`agent.pipeline` provider.

    Baseline behavior:
    - `config.mock_output` (dict) can force an exact output payload.
    - Otherwise derive a lightweight triage-style output from input fields.
    """

    provider_id = "agent.pipeline"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
        )

        output = config.get("mock_output")
        if output is None:
            severity = str(input.get("severity", "")).upper()
            risk = "high" if severity in {"S1", "P0"} else "med" if severity in {"S2", "P1"} else "low"
            title = str(input.get("title", "")).strip() or "No title"
            output = {
                "risk": risk,
                "summary": title,
                "labels": list(input.get("labels", [])) if isinstance(input.get("labels"), list) else [],
            }

        if not isinstance(output, dict):
            raise ProviderError(
                code="invalid_config",
                message="agent.pipeline expects config.mock_output to be an object",
                retryable=False,
            )

        handle.provider_data["status"] = ExecutionStatus.COMPLETED
        handle.provider_data["output"] = output
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        if handle.provider_data.get("cancelled"):
            raise ProviderError(code="cancelled", message="Invocation was cancelled", retryable=False)
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["cancelled"] = True
        handle.provider_data["status"] = ExecutionStatus.FAILED


class DashboardFormProvider(Provider):
    """`dashboard.form` provider.

    Baseline behavior merges input payload with optional `config.defaults`.
    """

    provider_id = "dashboard.form"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        defaults = config.get("defaults", {})
        if defaults is not None and not isinstance(defaults, dict):
            raise ProviderError(
                code="invalid_config",
                message="dashboard.form expects config.defaults to be an object",
                retryable=False,
            )
        output = dict(defaults or {})
        output.update(input)

        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.COMPLETED,
                "output": output,
            },
        )
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        if handle.provider_data.get("cancelled"):
            raise ProviderError(code="cancelled", message="Invocation was cancelled", retryable=False)
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["cancelled"] = True
        handle.provider_data["status"] = ExecutionStatus.FAILED


class HttpGitlabProvider(Provider):
    """`http.gitlab` provider.

    Baseline behavior returns deterministic issue metadata for local testing.
    """

    provider_id = "http.gitlab"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        prefix = str(config.get("ticket_prefix", "BPG"))
        issue_num = int(hashlib.sha256(context.idempotency_key.encode()).hexdigest()[:8], 16) % 100000
        ticket_id = config.get("ticket_id") or f"{prefix}-{issue_num:05d}"
        output = {
            "ticket_id": ticket_id,
            "url": str(config.get("issue_url", f"https://gitlab.local/issues/{ticket_id}")),
        }

        # Optional passthrough labels from input if the receiving type declares it.
        if isinstance(input.get("labels"), list):
            output["labels"] = input["labels"]

        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.COMPLETED,
                "output": output,
            },
        )
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        if handle.provider_data.get("cancelled"):
            raise ProviderError(code="cancelled", message="Invocation was cancelled", retryable=False)
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["cancelled"] = True
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        _ = config
        return {
            "services": [],
            "required_env": ["GITLAB_TOKEN"],
            "optional_env": ["GITLAB_BASE_URL"],
        }


class QueueKafkaProvider(Provider):
    """`queue.kafka` provider.

    Simulates publishing to Kafka and returns publish metadata.
    """

    provider_id = "queue.kafka"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        topic = config.get("topic") or input.get("topic")
        if not topic:
            raise ProviderError(
                code="invalid_config",
                message="queue.kafka requires a topic in config.topic or input.topic",
                retryable=False,
            )

        output = {
            "published": True,
            "topic": str(topic),
            "partition": int(config.get("partition", 0)),
            "offset": int(config.get("offset", 0)),
            "idempotency_key": context.idempotency_key,
        }
        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.COMPLETED,
                "output": output,
            },
        )
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        if handle.provider_data.get("cancelled"):
            raise ProviderError(code="cancelled", message="Invocation was cancelled", retryable=False)
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["cancelled"] = True
        handle.provider_data["status"] = ExecutionStatus.FAILED


class TimerDelayProvider(Provider):
    """`timer.delay` provider.

    Waits for the configured duration and returns a small timing payload.
    """

    provider_id = "timer.delay"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        duration = config.get("duration", input.get("duration", 0))
        try:
            duration_s = float(duration)
        except (TypeError, ValueError):
            raise ProviderError(
                code="invalid_config",
                message="timer.delay requires numeric duration seconds",
                retryable=False,
            )
        if duration_s < 0:
            raise ProviderError(
                code="invalid_config",
                message="timer.delay duration must be >= 0",
                retryable=False,
            )

        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.RUNNING,
                "duration_seconds": duration_s,
                "started_at": time.monotonic(),
            },
        )
        return handle

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        if handle.provider_data.get("cancelled"):
            return ExecutionStatus.FAILED
        duration_s = float(handle.provider_data.get("duration_seconds", 0.0))
        started_at = float(handle.provider_data.get("started_at", time.monotonic()))
        if time.monotonic() - started_at >= duration_s:
            handle.provider_data["status"] = ExecutionStatus.COMPLETED
        return handle.provider_data.get("status", ExecutionStatus.RUNNING)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        if handle.provider_data.get("cancelled"):
            raise ProviderError(code="cancelled", message="Invocation was cancelled", retryable=False)

        duration_s = float(handle.provider_data.get("duration_seconds", 0.0))
        started_at = float(handle.provider_data.get("started_at", time.monotonic()))
        elapsed = max(0.0, time.monotonic() - started_at)
        remaining = max(0.0, duration_s - elapsed)

        if timeout is not None and remaining > timeout:
            time.sleep(timeout)
            raise TimeoutError("timer.delay exceeded timeout")

        if remaining > 0:
            time.sleep(remaining)

        handle.provider_data["status"] = ExecutionStatus.COMPLETED
        return {"ok": True, "slept_seconds": duration_s}

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["cancelled"] = True
        handle.provider_data["status"] = ExecutionStatus.FAILED


class FlowLoopProvider(Provider):
    """`flow.loop` provider.

    Produces a bounded slice of `input.items` for deterministic iteration plans.
    """

    provider_id = "flow.loop"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        items = input.get("items", [])
        if not isinstance(items, list):
            raise ProviderError("invalid_input", "flow.loop expects input.items list", False)
        max_iterations = config.get("max_iterations", input.get("max_iterations", len(items)))
        try:
            bound = max(0, int(max_iterations))
        except (TypeError, ValueError):
            raise ProviderError("invalid_config", "flow.loop max_iterations must be an integer", False)
        bounded = items[:bound]
        output = {
            "items": bounded,
            "count": len(bounded),
            "truncated": len(items) > len(bounded),
        }
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class FlowFanoutProvider(Provider):
    """`flow.fanout` provider.

    Converts a list payload into branch envelopes for downstream processing.
    """

    provider_id = "flow.fanout"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        _ = config
        items = input.get("items", [])
        if not isinstance(items, list):
            raise ProviderError("invalid_input", "flow.fanout expects input.items list", False)
        branches = [{"index": i, "item": item} for i, item in enumerate(items)]
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.COMPLETED,
                "output": {"branches": branches, "count": len(branches)},
            },
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class FlowAwaitAllProvider(Provider):
    """`flow.await_all` provider.

    Aggregates fanout branch results back into a single list.
    """

    provider_id = "flow.await_all"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        _ = config
        results = input.get("results", [])
        if not isinstance(results, list):
            raise ProviderError("invalid_input", "flow.await_all expects input.results list", False)
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={
                "status": ExecutionStatus.COMPLETED,
                "output": {"results": results, "count": len(results)},
            },
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class BpgProcessCallProvider(Provider):
    """`bpg.process_call` provider.

    Triggers another deployed BPG process and returns child run metadata.
    """

    provider_id = "bpg.process_call"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        from pathlib import Path

        from bpg.runtime.engine import Engine
        from bpg.state.store import StateStore

        process_name = config.get("process_name")
        if not isinstance(process_name, str) or not process_name:
            raise ProviderError(
                code="invalid_config",
                message="bpg.process_call requires config.process_name",
                retryable=False,
            )
        state_dir = Path(str(config.get("state_dir", ".bpg-state")))
        store = StateStore(state_dir)
        process = store.load_process(process_name)
        if process is None:
            raise ProviderError(
                code="invalid_config",
                message=f"bpg.process_call target process {process_name!r} not found",
                retryable=False,
            )
        child_run_id = Engine(process=process, state_store=store).trigger(input)
        child_run = store.load_run(child_run_id) or {}
        output = {
            "child_process": process_name,
            "child_run_id": child_run_id,
            "status": child_run.get("status", "unknown"),
            "output": child_run.get("output"),
        }
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class MarkdownListProvider(Provider):
    """`fs.markdown_list` provider.

    Enumerates markdown files from a root directory and returns document payloads.
    """

    provider_id = "fs.markdown_list"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        root_dir_raw = (
            input.get("root_dir")
            or config.get("root_dir")
            or os.getenv("BPG_MARKDOWN_ROOT")
            or "."
        )
        if not isinstance(root_dir_raw, str) or not root_dir_raw.strip():
            raise ProviderError(
                code="invalid_input",
                message="fs.markdown_list requires root_dir as input or config",
                retryable=False,
            )
        root_dir = Path(root_dir_raw).expanduser().resolve()
        if not root_dir.exists() or not root_dir.is_dir():
            raise ProviderError(
                code="invalid_input",
                message=f"fs.markdown_list root_dir not found: {root_dir}",
                retryable=False,
            )

        glob_pattern = input.get("glob") or config.get("glob") or "**/*.md"
        if not isinstance(glob_pattern, str) or not glob_pattern.strip():
            raise ProviderError(
                code="invalid_input",
                message="fs.markdown_list glob must be a non-empty string",
                retryable=False,
            )

        documents: list[dict[str, Any]] = []
        for path in sorted(root_dir.glob(glob_pattern)):
            if not path.is_file():
                continue
            try:
                markdown = path.read_text(encoding="utf-8")
            except Exception as exc:
                raise ProviderError(
                    code="read_error",
                    message=f"failed to read markdown file {path}: {exc}",
                    retryable=False,
                )
            rel_path = str(path.relative_to(root_dir))
            source_id = hashlib.sha256(rel_path.encode("utf-8")).hexdigest()[:16]
            documents.append(
                {
                    "source_id": source_id,
                    "path": rel_path,
                    "markdown": markdown,
                    "metadata": {
                        "bytes": path.stat().st_size,
                    },
                }
            )

        output = {"documents": documents}
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class MarkdownChunkProvider(Provider):
    """`text.markdown_chunk` provider.

    Splits markdown documents into character windows with overlap.
    """

    provider_id = "text.markdown_chunk"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        docs = input.get("documents")
        if not isinstance(docs, list):
            raise ProviderError(
                code="invalid_input",
                message="text.markdown_chunk requires input.documents list",
                retryable=False,
            )

        chunk_size_raw = config.get("chunk_size", 1200)
        overlap_raw = config.get("overlap", 200)
        try:
            chunk_size = int(chunk_size_raw)
            overlap = int(overlap_raw)
        except (TypeError, ValueError):
            raise ProviderError(
                code="invalid_config",
                message="text.markdown_chunk chunk_size and overlap must be integers",
                retryable=False,
            )
        if chunk_size <= 0:
            raise ProviderError("invalid_config", "text.markdown_chunk chunk_size must be > 0", False)
        if overlap < 0 or overlap >= chunk_size:
            raise ProviderError(
                "invalid_config",
                "text.markdown_chunk overlap must be >= 0 and < chunk_size",
                False,
            )

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
            metadata = doc.get("metadata")
            if metadata is not None and not isinstance(metadata, dict):
                metadata = {}
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
                        "metadata": metadata or {},
                    }
                )
                if start + chunk_size >= len(markdown):
                    break

        output = {"chunks": chunks}
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class EmbedTextProvider(Provider):
    """`embed.text` provider.

    Produces deterministic vectors for chunk payloads or query payloads.
    """

    provider_id = "embed.text"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        _ = config
        if isinstance(input.get("chunks"), list):
            items: list[dict[str, Any]] = []
            for chunk in input["chunks"]:
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
            output = {"items": items}
        else:
            query = input.get("query")
            if not isinstance(query, str) or not query.strip():
                raise ProviderError(
                    code="invalid_input",
                    message="embed.text requires input.query string or input.chunks list",
                    retryable=False,
                )
            output = {
                "query": query,
                "vector": _embed_vector(query),
                "top_k": input.get("top_k"),
            }

        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class WeaviateUpsertProvider(Provider):
    """`weaviate.upsert` provider.

    Local baseline implementation writes records to a shared JSONL store.
    """

    provider_id = "weaviate.upsert"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        items = input.get("items")
        if not isinstance(items, list):
            raise ProviderError(
                code="invalid_input",
                message="weaviate.upsert requires input.items list",
                retryable=False,
            )

        store_path = _search_store_path(config)
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

        inserted = 0
        updated = 0
        failed = 0
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

        output = {"inserted": inserted, "updated": updated, "failed": failed}
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        _ = config
        return {
            "services": [],
            "required_env": [],
            "optional_env": ["BPG_SEARCH_STORE_DIR", "WEAVIATE_URL", "WEAVIATE_API_KEY"],
        }


class WeaviateHybridSearchProvider(Provider):
    """`weaviate.hybrid_search` provider.

    Local baseline implementation performs hybrid lexical+vector search over
    records produced by :class:`WeaviateUpsertProvider`.
    """

    provider_id = "weaviate.hybrid_search"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        query = input.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ProviderError(
                code="invalid_input",
                message="weaviate.hybrid_search requires input.query string",
                retryable=False,
            )
        query_vec = input.get("vector")
        if not isinstance(query_vec, list):
            raise ProviderError(
                code="invalid_input",
                message="weaviate.hybrid_search requires input.vector list<number>",
                retryable=False,
            )

        top_k_raw = input.get("top_k")
        if top_k_raw is None:
            top_k_raw = config.get("top_k", 8)
        alpha_raw = config.get("alpha")
        if alpha_raw is None:
            alpha_raw = 0.5
        try:
            top_k = max(1, int(top_k_raw))
            alpha = float(alpha_raw)
        except (TypeError, ValueError):
            raise ProviderError(
                code="invalid_config",
                message="weaviate.hybrid_search top_k/alpha must be numeric",
                retryable=False,
            )
        alpha = min(1.0, max(0.0, alpha))

        store_path = _search_store_path(config)
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
        for record in records:
            text = str(record.get("text", ""))
            lexical = _lexical_score(query, text)
            vec = record.get("vector")
            if isinstance(vec, list):
                vector_score = _cosine_similarity(
                    [float(v) for v in query_vec if isinstance(v, (int, float))],
                    [float(v) for v in vec if isinstance(v, (int, float))],
                )
            else:
                vector_score = 0.0
            hybrid = ((1.0 - alpha) * lexical) + (alpha * vector_score)
            scored.append((hybrid, record))

        scored.sort(key=lambda item: item[0], reverse=True)
        hits: list[dict[str, Any]] = []
        for score, record in scored[:top_k]:
            hits.append(
                {
                    "source_id": str(record.get("source_id", "")),
                    "chunk_id": str(record.get("chunk_id", "")),
                    "text": str(record.get("text", "")),
                    "score": float(score),
                    "metadata": record.get("metadata", {}) if isinstance(record.get("metadata"), dict) else {},
                }
            )

        output = {"query": query, "hits": hits}
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        _ = config
        return {
            "services": [],
            "required_env": [],
            "optional_env": ["BPG_SEARCH_STORE_DIR", "WEAVIATE_URL", "WEAVIATE_API_KEY"],
        }


class ParseTextNumbersProvider(Provider):
    """`text.parse_numbers` provider.

    Extracts numeric tokens from ``input.text`` and returns them as a list.
    """

    provider_id = "text.parse_numbers"
    _NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        _ = config
        text = input.get("text")
        if not isinstance(text, str):
            raise ProviderError(
                code="invalid_input",
                message="text.parse_numbers requires input.text string",
                retryable=False,
            )

        matches = self._NUMBER_RE.findall(text)
        numbers: list[float] = [float(token) for token in matches]
        output = {"numbers": numbers}
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(
        self, handle: ExecutionHandle, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class SumNumbersProvider(Provider):
    """`math.sum_numbers` provider.

    Sums ``input.numbers`` and returns ``sum`` plus ``count``.
    """

    provider_id = "math.sum_numbers"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        _ = config
        numbers = input.get("numbers")
        if not isinstance(numbers, list):
            raise ProviderError(
                code="invalid_input",
                message="math.sum_numbers requires input.numbers list",
                retryable=False,
            )
        for idx, value in enumerate(numbers):
            if not isinstance(value, (int, float)):
                raise ProviderError(
                    code="invalid_input",
                    message=f"math.sum_numbers input.numbers[{idx}] must be numeric",
                    retryable=False,
                )
        total = float(sum(numbers))
        output = {"sum": total, "count": len(numbers)}
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(
        self, handle: ExecutionHandle, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED


class WebSearchProvider(Provider):
    """`tool.web_search` provider.

    Dry run:
    - Returns deterministic placeholder results without external calls.
    Live mode:
    - Calls a configurable HTTP endpoint and normalizes JSON search results.
    """

    provider_id = "tool.web_search"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        query = input.get("query")
        if not isinstance(query, str) or not query.strip():
            raise ProviderError(
                code="invalid_input",
                message="tool.web_search requires input.query string",
                retryable=False,
            )

        top_k_raw = config.get("top_k", input.get("top_k", 5))
        try:
            top_k = max(1, int(top_k_raw))
        except (TypeError, ValueError):
            raise ProviderError(
                code="invalid_config",
                message="tool.web_search top_k must be an integer",
                retryable=False,
            )

        if _is_dry_run(config):
            results = []
            for idx in range(top_k):
                n = idx + 1
                results.append({
                    "title": f"Dry-run result {n} for: {query}",
                    "url": f"https://example.invalid/search/{n}",
                    "snippet": f"Synthetic search result {n} for query '{query}'.",
                })
            output = {"query": query, "results": results, "source": "dry-run"}
        else:
            endpoint = config.get("endpoint") or os.getenv("WEB_SEARCH_ENDPOINT")
            if not isinstance(endpoint, str) or not endpoint.strip():
                raise ProviderError(
                    code="invalid_config",
                    message="tool.web_search requires config.endpoint or WEB_SEARCH_ENDPOINT in live mode",
                    retryable=False,
                )

            api_key_env = str(config.get("api_key_env", "WEB_SEARCH_API_KEY"))
            require_api_key = bool(config.get("require_api_key", True))
            api_key = os.getenv(api_key_env)
            if require_api_key and not api_key:
                raise ProviderError(
                    code="invalid_config",
                    message=f"tool.web_search missing required env {api_key_env}",
                    retryable=False,
                )

            timeout = float(config.get("timeout_seconds", 10))
            params = {"q": query, "k": str(top_k)}
            req_url = f"{endpoint}?{urllib.parse.urlencode(params)}"
            headers = {"Accept": "application/json"}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            req = urllib.request.Request(req_url, headers=headers, method="GET")
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    payload = resp.read().decode("utf-8")
            except Exception as exc:
                raise ProviderError(
                    code="web_search_http_error",
                    message=str(exc),
                    retryable=True,
                )

            import json

            try:
                parsed = json.loads(payload)
            except json.JSONDecodeError as exc:
                raise ProviderError(
                    code="web_search_invalid_json",
                    message=str(exc),
                    retryable=False,
                )

            raw_results = parsed.get("results") if isinstance(parsed, dict) else parsed
            if not isinstance(raw_results, list):
                raise ProviderError(
                    code="web_search_invalid_response",
                    message="tool.web_search expected response list or {results: [...]}",
                    retryable=False,
                )
            results = []
            for item in raw_results[:top_k]:
                if not isinstance(item, dict):
                    continue
                results.append({
                    "title": str(item.get("title", "")),
                    "url": str(item.get("url", "")),
                    "snippet": str(item.get("snippet", item.get("description", ""))),
                })
            output = {"query": query, "results": results, "source": endpoint}

        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(
        self, handle: ExecutionHandle, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        if _is_dry_run(config):
            return {
                "services": [],
                "required_env": [],
                "optional_env": ["WEB_SEARCH_ENDPOINT", "WEB_SEARCH_API_KEY"],
            }
        api_key_env = str(config.get("api_key_env", "WEB_SEARCH_API_KEY"))
        require_api_key = bool(config.get("require_api_key", True))
        required = [api_key_env] if require_api_key else []
        optional = [] if require_api_key else [api_key_env]
        optional.append("WEB_SEARCH_ENDPOINT")
        return {"services": [], "required_env": required, "optional_env": optional}


class EmailNotifyProvider(Provider):
    """`notify.email` provider.

    Dry run:
    - Produces synthetic delivery metadata without sending mail.
    Live mode:
    - Sends via SMTP using config/env credentials.
    """

    provider_id = "notify.email"

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        to_addr = input.get("to")
        subject = input.get("subject")
        body = input.get("body")
        if not isinstance(to_addr, str) or "@" not in to_addr:
            raise ProviderError("invalid_input", "notify.email requires input.to email", False)
        if not isinstance(subject, str):
            raise ProviderError("invalid_input", "notify.email requires input.subject string", False)
        if not isinstance(body, str):
            raise ProviderError("invalid_input", "notify.email requires input.body string", False)

        from_addr = config.get("from") or os.getenv("SMTP_FROM")
        if not isinstance(from_addr, str) or "@" not in from_addr:
            raise ProviderError(
                code="invalid_config",
                message="notify.email requires config.from or SMTP_FROM",
                retryable=False,
            )

        if _is_dry_run(config):
            output = {
                "sent": False,
                "dry_run": True,
                "to": to_addr,
                "from": from_addr,
                "subject": subject,
                "message_id": f"dry-{context.idempotency_key[:16]}",
            }
        else:
            host = config.get("smtp_host") or os.getenv("SMTP_HOST")
            if not isinstance(host, str) or not host.strip():
                raise ProviderError(
                    code="invalid_config",
                    message="notify.email requires config.smtp_host or SMTP_HOST in live mode",
                    retryable=False,
                )

            port_raw = config.get("smtp_port", os.getenv("SMTP_PORT", "587"))
            try:
                port = int(port_raw)
            except (TypeError, ValueError):
                raise ProviderError(
                    code="invalid_config",
                    message="notify.email SMTP port must be an integer",
                    retryable=False,
                )
            username = config.get("smtp_username") or os.getenv("SMTP_USERNAME")
            password = config.get("smtp_password") or os.getenv("SMTP_PASSWORD")
            starttls = bool(config.get("smtp_starttls", True))

            msg = EmailMessage()
            msg["From"] = from_addr
            msg["To"] = to_addr
            msg["Subject"] = subject
            msg["X-BPG-Idempotency-Key"] = context.idempotency_key
            msg.set_content(body)

            try:
                with smtplib.SMTP(host=host, port=port, timeout=10) as client:
                    if starttls:
                        client.starttls()
                    if username:
                        client.login(username, password or "")
                    client.send_message(msg)
            except Exception as exc:
                raise ProviderError(
                    code="smtp_send_error",
                    message=str(exc),
                    retryable=True,
                )

            output = {
                "sent": True,
                "dry_run": False,
                "to": to_addr,
                "from": from_addr,
                "subject": subject,
                "message_id": f"smtp-{context.idempotency_key[:16]}",
            }

        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(
        self, handle: ExecutionHandle, timeout: Optional[float] = None
    ) -> Dict[str, Any]:
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        required: list[str] = []
        optional: list[str] = ["SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD"]
        if not config.get("from"):
            required.append("SMTP_FROM")
        else:
            optional.append("SMTP_FROM")
        if _is_dry_run(config):
            optional.append("SMTP_HOST")
            return {"services": [], "required_env": required, "optional_env": optional}
        required.append("SMTP_HOST")
        return {
            "services": [],
            "required_env": required,
            "optional_env": optional,
        }
