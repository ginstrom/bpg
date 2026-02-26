"""http.webhook provider — generic HTTP webhook send/receive.

Sends an HTTP POST to a configured URL carrying the input payload and
idempotency key.  Supports two modes:

Synchronous (default, ``async_mode: false``)
    The POST response body is the output payload.  ``invoke`` resolves
    immediately and ``poll`` always returns ``COMPLETED``.

Asynchronous (``async_mode: true``)
    The POST response body must contain a ``job_id`` field.  The provider
    polls ``{poll_url}/{job_id}`` until the remote server returns
    ``{"status": "completed", "output": {...}}`` or
    ``{"status": "failed", "error": {...}}``.

Config schema (all values are strings from YAML; types are validated at use)
----------------------------------------------------------------------------
    url          str            Webhook endpoint to POST the input payload to.
    headers      dict[str,str]? Additional HTTP headers (e.g. Authorization).
    async_mode   bool           Enable async polling mode (default: false).
    poll_url     str?           Base URL for async status checks; required when
                                async_mode is true.  Polled as ``{poll_url}/{job_id}``.
    cancel_url   str?           Base URL for cancellation requests.  Requested as
                                DELETE ``{cancel_url}/{job_id}``.
    poll_interval float         Seconds between poll attempts (default: 1.0).

Idempotency
-----------
The idempotency key from ``ExecutionContext`` is forwarded in the
``X-Idempotency-Key`` request header on every POST.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
    ProviderError,
)


class WebhookProvider(Provider):
    """HTTP webhook provider (``http.webhook``)."""

    provider_id = "http.webhook"

    # ------------------------------------------------------------------
    # invoke
    # ------------------------------------------------------------------

    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        """POST the input payload to the configured URL.

        The idempotency key is sent in the ``X-Idempotency-Key`` header.  In
        synchronous mode the response body is stored in the handle immediately.
        In async mode the response is expected to contain a ``job_id`` that
        is used by ``poll`` / ``await_result``.

        Raises:
            ProviderError: On HTTP error or malformed response.
        """
        url = _require(config, "url")
        async_mode = _bool(config.get("async_mode", False))
        extra_headers: Dict[str, str] = config.get("headers") or {}

        body = json.dumps(input, sort_keys=True).encode()
        headers = {
            "Content-Type": "application/json",
            "X-Idempotency-Key": context.idempotency_key,
            **extra_headers,
        }

        response_body = _http_post(url, body, headers)

        handle = ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
        )

        if async_mode:
            job_id = response_body.get("job_id")
            if not job_id:
                raise ProviderError(
                    code="invalid_response",
                    message="async_mode is true but POST response missing 'job_id'",
                    retryable=False,
                )
            handle.provider_data["job_id"] = job_id
            handle.provider_data["status"] = ExecutionStatus.RUNNING
        else:
            # Synchronous: response IS the output
            handle.provider_data["output"] = response_body
            handle.provider_data["status"] = ExecutionStatus.COMPLETED

        return handle

    # ------------------------------------------------------------------
    # poll
    # ------------------------------------------------------------------

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        """Return the current status without blocking.

        In synchronous mode this always returns ``COMPLETED``.  In async mode
        it makes one HTTP GET to the poll endpoint and updates the handle.

        Raises:
            ProviderError: On HTTP or protocol errors.
        """
        status = handle.provider_data.get("status", ExecutionStatus.RUNNING)
        if status != ExecutionStatus.RUNNING:
            return status

        # Async: fetch remote status
        job_id = handle.provider_data.get("job_id")
        if not job_id:
            # Should not happen in sync mode (status would already be COMPLETED)
            return ExecutionStatus.RUNNING

        poll_url = handle.provider_data.get("poll_url")
        if not poll_url:
            raise ProviderError(
                code="invalid_config",
                message="poll_url is required for async webhook polling",
                retryable=False,
            )

        status_body = _http_get(f"{poll_url}/{job_id}")
        return _parse_async_status(handle, status_body)

    # ------------------------------------------------------------------
    # await_result
    # ------------------------------------------------------------------

    def await_result(
        self,
        handle: ExecutionHandle,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Block until the execution completes and return the output payload.

        In synchronous mode this returns immediately.  In async mode it polls
        at the configured interval until complete or ``timeout`` is exceeded.

        Raises:
            ProviderError: If the remote execution failed.
            TimeoutError: If ``timeout`` seconds elapse before completion.
        """
        poll_interval: float = float(handle.provider_data.get("poll_interval", 1.0))
        deadline = (time.monotonic() + timeout) if timeout is not None else None

        while True:
            status = self.poll(handle)

            if status == ExecutionStatus.COMPLETED:
                output = handle.provider_data.get("output")
                if output is None:
                    raise ProviderError(
                        code="missing_output",
                        message="Execution completed but no output was recorded",
                        retryable=False,
                    )
                return output

            if status == ExecutionStatus.FAILED:
                error = handle.provider_data.get("error", {})
                raise ProviderError(
                    code=error.get("code", "provider_error"),
                    message=error.get("message", "Remote execution failed"),
                    retryable=error.get("retryable", False),
                )

            # Still RUNNING — check timeout before sleeping
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError(
                    f"Webhook execution did not complete within {timeout}s "
                    f"(handle={handle.handle_id})"
                )

            time.sleep(poll_interval)

    # ------------------------------------------------------------------
    # cancel
    # ------------------------------------------------------------------

    def cancel(self, handle: ExecutionHandle) -> None:
        """Send a DELETE request to the configured cancel URL, if any.

        No-op if no ``cancel_url`` is configured.

        Raises:
            ProviderError: If the cancel request fails.
        """
        cancel_url = handle.provider_data.get("cancel_url")
        if not cancel_url:
            return

        job_id = handle.provider_data.get("job_id", handle.handle_id)
        _http_delete(f"{cancel_url}/{job_id}")
        handle.provider_data["status"] = ExecutionStatus.FAILED


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require(config: Dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not value:
        raise ProviderError(
            code="invalid_config",
            message=f"http.webhook: required config field '{key}' is missing",
            retryable=False,
        )
    return str(value)


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).lower() in ("true", "1", "yes")


def _http_post(
    url: str,
    body: bytes,
    headers: Dict[str, str],
) -> Dict[str, Any]:
    req = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            detail = json.loads(raw).get("message", raw.decode())
        except Exception:
            detail = raw.decode(errors="replace")
        retryable = exc.code in (429, 500, 502, 503, 504)
        raise ProviderError(
            code=f"http_{exc.code}",
            message=f"POST {url} returned {exc.code}: {detail}",
            retryable=retryable,
        ) from exc
    except urllib.error.URLError as exc:
        raise ProviderError(
            code="provider_unavailable",
            message=f"POST {url} failed: {exc.reason}",
            retryable=True,
        ) from exc


def _http_get(url: str) -> Dict[str, Any]:
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req) as resp:
            raw = resp.read()
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        retryable = exc.code in (429, 500, 502, 503, 504)
        raise ProviderError(
            code=f"http_{exc.code}",
            message=f"GET {url} returned {exc.code}",
            retryable=retryable,
        ) from exc
    except urllib.error.URLError as exc:
        raise ProviderError(
            code="provider_unavailable",
            message=f"GET {url} failed: {exc.reason}",
            retryable=True,
        ) from exc


def _http_delete(url: str) -> None:
    req = urllib.request.Request(url, method="DELETE")
    try:
        with urllib.request.urlopen(req):
            pass
    except urllib.error.HTTPError as exc:
        raise ProviderError(
            code=f"http_{exc.code}",
            message=f"DELETE {url} returned {exc.code}",
            retryable=False,
        ) from exc
    except urllib.error.URLError as exc:
        raise ProviderError(
            code="provider_unavailable",
            message=f"DELETE {url} failed: {exc.reason}",
            retryable=False,
        ) from exc


def _parse_async_status(
    handle: ExecutionHandle,
    body: Dict[str, Any],
) -> ExecutionStatus:
    """Update handle state from an async poll response body."""
    remote_status = body.get("status", "running")

    if remote_status == "completed":
        handle.provider_data["output"] = body.get("output", {})
        handle.provider_data["status"] = ExecutionStatus.COMPLETED
        return ExecutionStatus.COMPLETED

    if remote_status == "failed":
        handle.provider_data["error"] = body.get("error", {})
        handle.provider_data["status"] = ExecutionStatus.FAILED
        return ExecutionStatus.FAILED

    return ExecutionStatus.RUNNING
