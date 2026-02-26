"""Provider base class and shared types for the BPG provider abstraction layer.

Every provider MUST implement:

    invoke(input, config, context) -> ExecutionHandle
    poll(handle)                   -> ExecutionStatus
    await_(handle, timeout)        -> TypedOutput
    cancel(handle)                 -> None

Idempotency (§8)
----------------
Every invoke call is keyed before reaching the provider.  The key is computed
deterministically from the run context and input payload:

    idempotency_key = sha256(run_id + ":" + node_name + ":" + canonical_json(input))

Callers compute the key via ``compute_idempotency_key`` and embed it in the
``ExecutionContext`` before calling ``Provider.invoke``.  Providers MUST
forward this key to external systems so that repeated calls are safe to retry.
"""

from __future__ import annotations

import hashlib
import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, ClassVar, Dict, Optional


# ---------------------------------------------------------------------------
# Idempotency key
# ---------------------------------------------------------------------------

def compute_idempotency_key(
    run_id: str,
    node_name: str,
    input_payload: Dict[str, Any],
) -> str:
    """Compute a deterministic idempotency key for a node invocation.

    The canonical JSON form sorts object keys and omits whitespace, so the
    same logical payload always produces the same key regardless of dict
    insertion order.

    Args:
        run_id: Globally unique run identifier (UUID4).
        node_name: Name of the node instance being invoked.
        input_payload: Fully-resolved input payload (stable fields only).

    Returns:
        64-character lowercase hexadecimal SHA-256 digest.
    """
    canonical = json.dumps(input_payload, sort_keys=True, separators=(",", ":"))
    raw = f"{run_id}:{node_name}:{canonical}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Execution status
# ---------------------------------------------------------------------------

class ExecutionStatus(str, Enum):
    """Status of an in-flight provider execution as seen by ``poll``."""

    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


# ---------------------------------------------------------------------------
# Execution context
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ExecutionContext:
    """Immutable runtime context passed to every provider invocation.

    The idempotency key MUST be computed by the caller (typically the engine)
    via ``compute_idempotency_key`` before constructing this object.

    Attributes:
        run_id: Globally unique run identifier.
        node_name: Node instance name being executed.
        idempotency_key: Pre-computed key (see ``compute_idempotency_key``).
        process_name: Name of the owning process (informational only).
    """

    run_id: str
    node_name: str
    idempotency_key: str
    process_name: Optional[str] = None


# ---------------------------------------------------------------------------
# Execution handle
# ---------------------------------------------------------------------------

@dataclass
class ExecutionHandle:
    """Opaque reference to an in-flight provider execution.

    Returned by ``Provider.invoke`` and used with ``poll``, ``await_result``,
    and ``cancel``.  The ``provider_data`` dict holds any provider-specific
    state needed to track the execution (e.g. a remote job ID, a cached
    synchronous result).

    Attributes:
        handle_id: Unique ID for this execution (defaults to idempotency key).
        idempotency_key: The key forwarded to the external system.
        provider_id: Identifier of the provider that created this handle.
        provider_data: Mutable provider-specific bookkeeping.
    """

    handle_id: str
    idempotency_key: str
    provider_id: str
    provider_data: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Provider error
# ---------------------------------------------------------------------------

@dataclass
class ProviderError(Exception):
    """Typed error surfaced by a provider.

    Providers MUST raise ``ProviderError`` instead of raw exceptions so the
    engine can apply typed retry logic (§10) and record structured failure
    information in the run log.

    Attributes:
        code: Short machine-readable error code, e.g. ``"rate_limit"``.
        message: Human-readable description of the failure.
        retryable: Whether the engine may safely retry this invocation.
    """

    code: str
    message: str
    retryable: bool = False

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"

    def __hash__(self) -> int:
        return hash((self.code, self.message, self.retryable))


# ---------------------------------------------------------------------------
# Provider ABC
# ---------------------------------------------------------------------------

class Provider(ABC):
    """Abstract base class for all BPG execution providers.

    Providers are pluggable backends that carry out work on behalf of a BPG
    node.  Each concrete provider is identified by a ``provider_id`` class
    variable and registered in the ``PROVIDER_REGISTRY`` in ``__init__.py``.

    Lifecycle
    ---------
    1. Engine calls ``compute_idempotency_key`` and builds ``ExecutionContext``.
    2. Engine calls ``provider.invoke(input, config, context)`` → handle.
    3. Engine calls ``provider.poll(handle)`` or ``provider.await_(handle)``
       to get the output.
    4. On cancellation, engine calls ``provider.cancel(handle)``.

    Providers MUST be stateless with respect to process logic.  All execution
    state lives in the BPG runtime, not inside the provider instance.
    """

    #: Unique identifier for this provider type, e.g. ``"http.webhook"``.
    provider_id: ClassVar[str]

    @abstractmethod
    def invoke(
        self,
        input: Dict[str, Any],
        config: Dict[str, Any],
        context: ExecutionContext,
    ) -> ExecutionHandle:
        """Start executing work and return an opaque handle.

        The ``context.idempotency_key`` MUST be forwarded to the external
        system (e.g. as a header or request field) so repeated calls with the
        same key do not create duplicate side effects.

        Args:
            input: Validated input payload conforming to the node's ``in`` type.
            config: Provider configuration from the node instance.
            context: Runtime context including the pre-computed idempotency key.

        Returns:
            An ``ExecutionHandle`` for tracking this execution.

        Raises:
            ProviderError: If the invocation fails immediately.
        """

    @abstractmethod
    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        """Return the current status of an in-flight execution without blocking.

        Args:
            handle: The handle returned by ``invoke``.

        Returns:
            Current ``ExecutionStatus``.

        Raises:
            ProviderError: On communication or protocol errors.
        """

    @abstractmethod
    def await_result(
        self,
        handle: ExecutionHandle,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Block until execution completes and return the output payload.

        Args:
            handle: The handle returned by ``invoke``.
            timeout: Maximum seconds to wait; ``None`` means wait indefinitely.

        Returns:
            Output payload conforming to the node's ``out`` type.

        Raises:
            ProviderError: If the execution failed.
            TimeoutError: If ``timeout`` is exceeded before completion.
        """

    def await_(
        self,
        handle: ExecutionHandle,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Spec-aligned alias for awaiting provider completion.

        Python reserves ``await`` as a keyword, so the provider contract uses
        ``await_`` as the canonical callable name while preserving
        ``await_result`` for backward compatibility.
        """
        return self.await_result(handle, timeout=timeout)

    @abstractmethod
    def cancel(self, handle: ExecutionHandle) -> None:
        """Request cancellation of an in-flight execution.

        The provider makes a best-effort attempt to stop work but is not
        required to guarantee termination.  After this call the handle is
        invalid and MUST NOT be passed to ``poll`` or ``await_result``.

        Args:
            handle: The handle returned by ``invoke``.

        Raises:
            ProviderError: If the cancel request cannot be delivered.
        """

    def deploy(
        self,
        node_name: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Deploy provider artifacts for a node instance.

        Called by ``bpg apply`` for every added or modified node.  Providers that
        need to register external resources (e.g. webhook endpoints, queue
        subscriptions) override this method.

        Args:
            node_name: The node instance name being deployed.
            config: Provider configuration from the node instance.

        Returns:
            A dict of deployment artifact metadata to persist in state
            (e.g. ``{"registered_url": "https://..."}``).  Return ``{}`` for
            providers that need no external registration.

        Raises:
            ProviderError: If deployment fails.
        """
        return {}

    def undeploy(
        self,
        node_name: str,
        config: Dict[str, Any],
        artifacts: Dict[str, Any],
    ) -> None:
        """Remove provider artifacts for a node instance.

        Called by ``bpg apply`` for every removed node.  Providers override this
        to deregister external resources they created in ``deploy``.

        Args:
            node_name: The node instance name being removed.
            config: Provider configuration from the node instance.
            artifacts: The artifacts dict that was returned by ``deploy``.

        Raises:
            ProviderError: If teardown fails.
        """
