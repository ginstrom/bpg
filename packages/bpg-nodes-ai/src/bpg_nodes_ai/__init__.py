"""AI/LLM BPG nodes backed by Anthropic, OpenAI, Google, and Ollama."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from bpg_sdk import node
from bpg_sdk.manifest import Idempotency, ObservabilitySupport, RetrySafety, SideEffects

_PKG = "bpg.nodes.ai@v1"

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}

_AI_INPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "model": {"type": "string"},
        "system_prompt": {"type": "string"},
        "prompt_template": {"type": "string"},
        "context_fields": {"type": "array"},
        "api_key_env": {"type": "string"},
        "max_tokens": {"type": "integer"},
        "temperature": {"type": "number"},
        "dry_run": {"type": "boolean"},
        "mock_output": {"type": "object"},
        "output_schema": {"type": "object"},
    },
    "required": ["model"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_dry_run(payload: dict[str, Any]) -> bool:
    raw = payload.get("dry_run")
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return os.getenv("BPG_DRY_RUN", "").strip().lower() in {"1", "true", "yes", "on"}


def _normalize_input(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _build_prompt(payload: dict[str, Any]) -> str:
    context_fields = payload.get("context_fields")
    if isinstance(context_fields, list):
        selected = {k: payload[k] for k in context_fields if k in payload}
        input_part = _normalize_input(selected if selected else payload)
    else:
        excluded = {
            "model", "system_prompt", "prompt_template", "context_fields",
            "api_key_env", "max_tokens", "temperature", "dry_run", "mock_output",
            "output_schema", "base_url", "anthropic_version",
        }
        input_part = _normalize_input({k: v for k, v in payload.items() if k not in excluded})

    prompt_template = payload.get("prompt_template")
    if isinstance(prompt_template, str) and prompt_template.strip():
        return prompt_template.replace("{{input}}", input_part)
    return input_part


def _parse_llm_json(text: str) -> dict[str, Any]:
    def _try(raw: str) -> Any:
        try:
            return json.loads(raw)
        except Exception:
            return None

    parsed = _try(text)
    if isinstance(parsed, dict):
        return parsed

    fenced = _JSON_BLOCK_RE.search(text)
    if fenced:
        parsed = _try(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    start, end = text.find("{"), text.rfind("}")
    if 0 <= start < end:
        parsed = _try(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed

    raise ValueError("AI provider expected model output to contain a JSON object")


def _http_post_json(url: str, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        code = exc.code
        try:
            detail = exc.read().decode("utf-8", errors="replace")
        except Exception:
            detail = str(exc.reason)
        retryable = code in _RETRYABLE_HTTP_CODES
        raise (OSError if retryable else ValueError)(f"HTTP {code}: {detail}") from exc
    except Exception as exc:
        raise OSError(f"HTTP request failed: {exc}") from exc


def _read_api_key(payload: dict[str, Any], default_env: str) -> str:
    env_var = str(payload.get("api_key_env", default_env)).strip()
    if not env_var:
        return ""
    key = os.getenv(env_var)
    if not key:
        raise ValueError(f"AI node missing required env {env_var}")
    return key


def _base_url(payload: dict[str, Any], default_url: str) -> str:
    return str(payload.get("base_url", default_url)).strip() or default_url


def _int_param(value: Any, default: int) -> int:
    try:
        return int(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _float_param(value: Any, default: float) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

@node(
    package=_PKG,
    node_id="anthropic",
    input_schema=_AI_INPUT_SCHEMA,
    output_schema={"type": "object"},
    capabilities=["llm"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
    observability=ObservabilitySupport.REQUIRED,
)
def anthropic(payload: dict[str, Any]) -> dict[str, Any]:
    if _is_dry_run(payload):
        output = payload.get("mock_output") or {"text": _normalize_input(
            {k: v for k, v in payload.items() if k not in {"model", "system_prompt", "dry_run"}}
        )}
        return dict(output)

    model = str(payload.get("model", "")).strip()
    if not model:
        raise ValueError("anthropic requires model")

    api_key = _read_api_key(payload, "ANTHROPIC_API_KEY")
    endpoint = _base_url(payload, "https://api.anthropic.com/v1/messages")
    max_tokens = _int_param(payload.get("max_tokens"), 1024)
    temperature = _float_param(payload.get("temperature"), 0.0)
    system_prompt = str(payload.get("system_prompt", "")).strip()
    anthropic_version = str(payload.get("anthropic_version", "2023-06-01"))

    req_payload: dict[str, Any] = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [{"role": "user", "content": _build_prompt(payload)}],
    }
    if system_prompt:
        req_payload["system"] = system_prompt

    response = _http_post_json(
        endpoint,
        req_payload,
        {
            "content-type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": anthropic_version,
        },
    )

    content = response.get("content")
    if not isinstance(content, list):
        raise ValueError("anthropic response missing content array")
    text = "\n".join(
        item["text"]
        for item in content
        if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str)
    ).strip()
    if not text:
        raise ValueError("anthropic response did not include text content")
    return _parse_llm_json(text)


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------

@node(
    package=_PKG,
    node_id="openai",
    input_schema=_AI_INPUT_SCHEMA,
    output_schema={"type": "object"},
    capabilities=["llm"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
    observability=ObservabilitySupport.REQUIRED,
)
def openai(payload: dict[str, Any]) -> dict[str, Any]:
    if _is_dry_run(payload):
        output = payload.get("mock_output") or {"text": _normalize_input(
            {k: v for k, v in payload.items() if k not in {"model", "system_prompt", "dry_run"}}
        )}
        return dict(output)

    model = str(payload.get("model", "")).strip()
    if not model:
        raise ValueError("openai requires model")

    api_key = _read_api_key(payload, "OPENAI_API_KEY")
    endpoint = _base_url(payload, "https://api.openai.com/v1/responses")
    max_tokens = _int_param(payload.get("max_tokens"), 1024)
    temperature = _float_param(payload.get("temperature"), 0.0)
    system_prompt = str(payload.get("system_prompt", "")).strip()

    req_payload: dict[str, Any] = {
        "model": model,
        "input": [{"role": "user", "content": [{"type": "input_text", "text": _build_prompt(payload)}]}],
        "temperature": temperature,
        "max_output_tokens": max_tokens,
    }
    if system_prompt:
        req_payload["instructions"] = system_prompt

    response = _http_post_json(
        endpoint,
        req_payload,
        {"content-type": "application/json", "authorization": f"Bearer {api_key}"},
    )

    output_items = response.get("output")
    if not isinstance(output_items, list):
        raise ValueError("openai response missing output array")
    text_parts: list[str] = []
    for item in output_items:
        if not isinstance(item, dict):
            continue
        for content_item in item.get("content", []):
            if isinstance(content_item, dict) and content_item.get("type") == "output_text":
                text_parts.append(str(content_item.get("text", "")))
    text = "\n".join(text_parts).strip()
    if not text:
        raise ValueError("openai response did not include output text")
    return _parse_llm_json(text)


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------

@node(
    package=_PKG,
    node_id="google",
    input_schema=_AI_INPUT_SCHEMA,
    output_schema={"type": "object"},
    capabilities=["llm"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
    observability=ObservabilitySupport.REQUIRED,
)
def google(payload: dict[str, Any]) -> dict[str, Any]:
    if _is_dry_run(payload):
        output = payload.get("mock_output") or {"text": _normalize_input(
            {k: v for k, v in payload.items() if k not in {"model", "system_prompt", "dry_run"}}
        )}
        return dict(output)

    model = str(payload.get("model", "")).strip()
    if not model:
        raise ValueError("google requires model")

    api_key = _read_api_key(payload, "GOOGLE_API_KEY")
    base_url_tmpl = _base_url(
        payload,
        "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
    )
    endpoint = base_url_tmpl.format(model=model)
    endpoint = f"{endpoint}?key={urllib.parse.quote(api_key)}"

    max_tokens = _int_param(payload.get("max_tokens"), 1024)
    temperature = _float_param(payload.get("temperature"), 0.0)
    system_prompt = str(payload.get("system_prompt", "")).strip()

    req_payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": _build_prompt(payload)}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    if system_prompt:
        req_payload["systemInstruction"] = {"parts": [{"text": system_prompt}]}

    response = _http_post_json(endpoint, req_payload, {"content-type": "application/json"})

    candidates = response.get("candidates")
    if not isinstance(candidates, list) or not candidates:
        raise ValueError("google response missing candidates")
    first = candidates[0]
    if not isinstance(first, dict):
        raise ValueError("google response has invalid candidate")
    parts = first.get("content", {}).get("parts", [])
    if not isinstance(parts, list):
        raise ValueError("google response missing content parts")
    text = "\n".join(p.get("text", "") for p in parts if isinstance(p, dict)).strip()
    if not text:
        raise ValueError("google response did not include text content")
    return _parse_llm_json(text)


# ---------------------------------------------------------------------------
# Ollama
# ---------------------------------------------------------------------------

@node(
    package=_PKG,
    node_id="ollama",
    input_schema=_AI_INPUT_SCHEMA,
    output_schema={"type": "object"},
    capabilities=["llm"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
    observability=ObservabilitySupport.REQUIRED,
)
def ollama(payload: dict[str, Any]) -> dict[str, Any]:
    if _is_dry_run(payload):
        output = payload.get("mock_output") or {"text": _normalize_input(
            {k: v for k, v in payload.items() if k not in {"model", "system_prompt", "dry_run"}}
        )}
        return dict(output)

    model = str(payload.get("model", "")).strip()
    if not model:
        raise ValueError("ollama requires model")

    endpoint = _base_url(payload, "http://localhost:11434/api/generate")
    max_tokens = _int_param(payload.get("max_tokens"), 1024)
    temperature = _float_param(payload.get("temperature"), 0.0)
    system_prompt = str(payload.get("system_prompt", "")).strip()

    req_payload: dict[str, Any] = {
        "model": model,
        "prompt": _build_prompt(payload),
        "stream": False,
        "options": {"temperature": temperature, "num_predict": max_tokens},
    }
    if system_prompt:
        req_payload["system"] = system_prompt

    response = _http_post_json(endpoint, req_payload, {"content-type": "application/json"})

    text = str(response.get("response", "")).strip()
    if not text:
        raise ValueError("ollama response did not include text content")
    return _parse_llm_json(text)


# ---------------------------------------------------------------------------
# LLM alias (defaults to anthropic)
# ---------------------------------------------------------------------------

@node(
    package=_PKG,
    node_id="llm",
    input_schema=_AI_INPUT_SCHEMA,
    output_schema={"type": "object"},
    capabilities=["llm"],
    side_effects=SideEffects.EXTERNAL,
    idempotency=Idempotency.CONDITIONAL,
    retry_safety=RetrySafety.CONDITIONAL,
    observability=ObservabilitySupport.REQUIRED,
)
def llm(payload: dict[str, Any]) -> dict[str, Any]:
    """Generic LLM node — delegates to the Anthropic implementation."""
    return anthropic.run(payload)


__all__ = [
    "anthropic",
    "openai",
    "google",
    "ollama",
    "llm",
]
