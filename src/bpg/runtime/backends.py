from __future__ import annotations

from typing import Any, Callable, Dict, Protocol


class ExecutionBackend(Protocol):
    """Backend contract for executing a process run.

    Backends encapsulate engine-specific execution mechanics. Runtime semantics
    (run records, audit policy, event persistence) remain in BPG runtime.
    """

    name: str

    def run(
        self,
        *,
        process: Any,
        state_store: Any,
        run_id: str,
        input_payload: Dict[str, Any],
        cached_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        """Execute one full process run and return backend final state."""


class _BackendFactory(Protocol):
    def __call__(self) -> ExecutionBackend:
        ...


def _temporal_factory() -> ExecutionBackend:
    try:
        from bpg_temporal import TemporalExecutionBackend
    except ImportError:
        from bpg.engines.local.backend import LocalExecutionBackend

        class _FallbackTemporalExecutionBackend(LocalExecutionBackend):
            name = "temporal"

        return _FallbackTemporalExecutionBackend()

    return TemporalExecutionBackend()


_BACKEND_FACTORIES: Dict[str, Callable[[], ExecutionBackend]] = {
    "temporal": _temporal_factory,
}


def available_backends() -> list[str]:
    """Return sorted backend names that can be selected at runtime."""
    return sorted(_BACKEND_FACTORIES.keys())


def get_backend(name: str) -> ExecutionBackend:
    """Resolve a named backend instance.

    Raises:
        ValueError: If the backend name is not registered.
    """
    factory = _BACKEND_FACTORIES.get(name)
    if factory is None:
        supported = ", ".join(available_backends())
        raise ValueError(f"Unknown engine backend {name!r}. Supported backends: {supported}")
    return factory()
