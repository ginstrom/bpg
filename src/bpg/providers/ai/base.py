from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from abc import abstractmethod
from typing import Any, Dict, Optional

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
    ProviderError,
)
from bpg.providers.metadata import (
    ProviderExample,
    ProviderIdempotency,
    ProviderLatencyClass,
    ProviderMetadata,
    ProviderSideEffects,
)

_JSON_BLOCK_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL)
_RETRYABLE_HTTP_CODES = {429, 500, 502, 503, 504}


class BaseAiProvider(Provider):
    provider_id = "ai.base"
    provider_description = "Structured-output LLM provider"
    default_api_key_env = ""
    default_base_url = ""

    @classmethod
    def metadata(cls) -> ProviderMetadata:
        return ProviderMetadata(
            name=cls.provider_id,
            description=cls.provider_description,
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            side_effects=ProviderSideEffects.EXTERNAL,
            idempotency=ProviderIdempotency.CONDITIONAL,
            latency_class=ProviderLatencyClass.HIGH,
            examples=[
                ProviderExample(
                    title=f"{cls.provider_id}-json-output",
                    config={
                        "model": "example-model",
                        "system_prompt": "Extract fields and return strict JSON.",
                        "prompt_template": "Input:\n{{input}}",
                        "output_schema": {
                            "type": "object",
                            "required": ["risk"],
                            "properties": {"risk": {"type": "string"}},
                        },
                    },
                    input={"text": "Urgent production outage"},
                )
            ],
        )

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        output_schema = config.get("output_schema")
        if output_schema is not None and not isinstance(output_schema, dict):
            raise ProviderError(
                code="invalid_config",
                message=f"{self.provider_id} expects config.output_schema to be an object",
                retryable=False,
            )

        if _is_truthy(config.get("dry_run")):
            output = config.get("mock_output")
            if output is None:
                output = {"text": _normalize_input(input)}
            _validate_schema(output, output_schema)
            return _completed_handle(self.provider_id, context.idempotency_key, output)

        model = str(config.get("model", "")).strip()
        if not model:
            raise ProviderError(
                code="invalid_config",
                message=f"{self.provider_id} requires config.model",
                retryable=False,
            )

        prompt = _build_prompt(input, config)
        raw_response = self._call_model(model=model, prompt=prompt, config=config, context=context)
        text = self._extract_text(raw_response)
        output = _parse_llm_json(text)
        _validate_schema(output, output_schema)
        return _completed_handle(self.provider_id, context.idempotency_key, output)

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return handle.provider_data.get("status", ExecutionStatus.COMPLETED)

    def await_result(self, handle: ExecutionHandle, timeout: Optional[float] = None) -> Dict[str, Any]:
        _ = timeout
        output = handle.provider_data.get("output", {})
        if not isinstance(output, dict):
            raise ProviderError(
                code="llm_invalid_response",
                message=f"{self.provider_id} produced non-object output",
                retryable=False,
            )
        return dict(output)

    def cancel(self, handle: ExecutionHandle) -> None:
        handle.provider_data["status"] = ExecutionStatus.FAILED

    def packaging_requirements(self, config: Dict[str, Any]) -> Dict[str, Any]:
        api_key_env = self._resolve_api_key_env(config)
        if _is_truthy(config.get("dry_run")):
            optional_env = [api_key_env] if api_key_env else []
            return {"services": [], "required_env": [], "optional_env": optional_env}
        required_env = [api_key_env] if api_key_env else []
        return {"services": [], "required_env": required_env, "optional_env": []}

    def _resolve_api_key_env(self, config: Dict[str, Any]) -> str:
        if not self.default_api_key_env:
            return ""
        return str(config.get("api_key_env", self.default_api_key_env)).strip()

    def _read_api_key(self, config: Dict[str, Any]) -> str:
        api_key_env = self._resolve_api_key_env(config)
        if not api_key_env:
            return ""
        api_key = os.getenv(api_key_env)
        if not api_key:
            raise ProviderError(
                code="missing_api_key",
                message=f"{self.provider_id} missing required env {api_key_env}",
                retryable=False,
            )
        return api_key

    def _base_url(self, config: Dict[str, Any]) -> str:
        return str(config.get("base_url", self.default_base_url)).strip()

    def _http_post_json(
        self,
        *,
        endpoint: str,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        error_label: str,
    ) -> Dict[str, Any]:
        body = json.dumps(payload, sort_keys=True).encode("utf-8")
        req = urllib.request.Request(
            endpoint,
            data=body,
            method="POST",
            headers=headers,
        )
        try:
            with urllib.request.urlopen(req) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = _read_http_error_detail(exc)
            raise ProviderError(
                code="llm_http_error",
                message=f"{error_label} request failed with HTTP {exc.code}: {detail}",
                retryable=exc.code in _RETRYABLE_HTTP_CODES,
            ) from exc
        except urllib.error.URLError as exc:
            raise ProviderError(
                code="llm_http_error",
                message=f"{error_label} request failed: {exc.reason}",
                retryable=True,
            ) from exc

        try:
            parsed = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ProviderError(
                code="llm_invalid_response",
                message=f"{error_label} returned invalid JSON: {exc}",
                retryable=False,
            ) from exc

        if not isinstance(parsed, dict):
            raise ProviderError(
                code="llm_invalid_response",
                message=f"{error_label} returned a non-object payload",
                retryable=False,
            )
        return parsed

    @abstractmethod
    def _call_model(
        self,
        *,
        model: str,
        prompt: str,
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> Dict[str, Any]:
        pass

    @abstractmethod
    def _extract_text(self, response: Dict[str, Any]) -> str:
        pass


def _completed_handle(provider_id: str, idempotency_key: str, output: Dict[str, Any]) -> ExecutionHandle:
    return ExecutionHandle(
        handle_id=idempotency_key,
        idempotency_key=idempotency_key,
        provider_id=provider_id,
        provider_data={"status": ExecutionStatus.COMPLETED, "output": output},
    )


def _build_prompt(input_payload: Dict[str, Any], config: Dict[str, Any]) -> str:
    prompt_template = config.get("prompt_template")
    selected = _select_context_fields(input_payload, config.get("context_fields"))
    normalized = _normalize_input(selected)
    if isinstance(prompt_template, str) and prompt_template.strip():
        return prompt_template.replace("{{input}}", normalized)
    return normalized


def _select_context_fields(payload: Dict[str, Any], raw_fields: Any) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"value": payload}
    if not isinstance(raw_fields, list):
        return payload
    selected: Dict[str, Any] = {}
    for item in raw_fields:
        if isinstance(item, str) and item in payload:
            selected[item] = payload[item]
    return selected if selected else payload


def _normalize_input(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, ensure_ascii=False)


def _parse_llm_json(text: str) -> Dict[str, Any]:
    parsed = _try_parse_json(text)
    if isinstance(parsed, dict):
        return parsed

    fenced = _JSON_BLOCK_RE.search(text)
    if fenced:
        parsed = _try_parse_json(fenced.group(1))
        if isinstance(parsed, dict):
            return parsed

    start = text.find("{")
    end = text.rfind("}")
    if 0 <= start < end:
        parsed = _try_parse_json(text[start : end + 1])
        if isinstance(parsed, dict):
            return parsed

    raise ProviderError(
        code="llm_output_not_json",
        message="ai provider expected model output to contain a JSON object",
        retryable=False,
    )


def _try_parse_json(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return None


def _read_http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        body = exc.read().decode("utf-8", errors="replace")
    except Exception:
        return str(exc.reason)
    try:
        payload = json.loads(body)
        if isinstance(payload, dict):
            if isinstance(payload.get("error"), dict):
                return str(payload["error"].get("message", body))
            if isinstance(payload.get("message"), str):
                return payload["message"]
    except Exception:
        pass
    return body


def _validate_schema(value: Any, schema: Any) -> None:
    if schema is None:
        return
    errors = _validate_schema_inner(value, schema, "$")
    if errors:
        raise ProviderError(
            code="llm_output_schema",
            message=f"ai output failed schema checks: {errors[0]}",
            retryable=False,
        )


def _validate_schema_inner(value: Any, schema: Any, path: str) -> list[str]:
    if not isinstance(schema, dict):
        return [f"{path}: schema must be an object"]

    errors: list[str] = []
    expected_type = schema.get("type")
    if isinstance(expected_type, str):
        type_error = _validate_type(value, expected_type, path)
        if type_error:
            errors.append(type_error)
            return errors

    if "enum" in schema and isinstance(schema["enum"], list):
        if value not in schema["enum"]:
            errors.append(f"{path}: expected one of {schema['enum']}, got {value!r}")

    if isinstance(value, dict):
        required = schema.get("required")
        if isinstance(required, list):
            for field in required:
                if isinstance(field, str) and field not in value:
                    errors.append(f"{path}.{field}: required field missing")

        properties = schema.get("properties")
        if isinstance(properties, dict):
            for key, child_schema in properties.items():
                if key in value:
                    errors.extend(_validate_schema_inner(value[key], child_schema, f"{path}.{key}"))

    if isinstance(value, list) and isinstance(schema.get("items"), dict):
        item_schema = schema["items"]
        for idx, item in enumerate(value):
            errors.extend(_validate_schema_inner(item, item_schema, f"{path}[{idx}]") )

    return errors


def _validate_type(value: Any, expected_type: str, path: str) -> str | None:
    if expected_type == "object" and not isinstance(value, dict):
        return f"{path}: expected object, got {type(value).__name__}"
    if expected_type == "array" and not isinstance(value, list):
        return f"{path}: expected array, got {type(value).__name__}"
    if expected_type == "string" and not isinstance(value, str):
        return f"{path}: expected string, got {type(value).__name__}"
    if expected_type == "boolean" and not isinstance(value, bool):
        return f"{path}: expected boolean, got {type(value).__name__}"
    if expected_type == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
        return f"{path}: expected integer, got {type(value).__name__}"
    if expected_type == "number" and not (
        (isinstance(value, int) and not isinstance(value, bool)) or isinstance(value, float)
    ):
        return f"{path}: expected number, got {type(value).__name__}"
    return None


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return False


def _int_or_default(value: Any, default: int, field: str, provider_id: str) -> int:
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            code="invalid_config",
            message=f"{provider_id} expected {field} to be an integer",
            retryable=False,
        ) from exc


def _float_or_default(value: Any, default: float, field: str, provider_id: str) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderError(
            code="invalid_config",
            message=f"{provider_id} expected {field} to be a number",
            retryable=False,
        ) from exc


def append_query_params(url: str, params: Dict[str, str]) -> str:
    parsed = urllib.parse.urlparse(url)
    query = dict(urllib.parse.parse_qsl(parsed.query, keep_blank_values=True))
    query.update({k: v for k, v in params.items() if v})
    return urllib.parse.urlunparse(parsed._replace(query=urllib.parse.urlencode(query)))
