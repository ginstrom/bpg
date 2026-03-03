from __future__ import annotations

from typing import Any, Dict

from bpg.engines.langgraph.backend import LangGraphExecutionBackend


class LocalExecutionBackend:
    """Local backend used to prove backend pluggability.

    This backend intentionally shares the same execution semantics path as the
    LangGraph backend for now, while exposing a distinct backend identity and
    selection path (`--engine local`).
    """

    name = "local"

    def __init__(self) -> None:
        self._delegate = LangGraphExecutionBackend()

    def run(
        self,
        *,
        process: Any,
        state_store: Any,
        run_id: str,
        input_payload: Dict[str, Any],
        cached_results: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        return self._delegate.run(
            process=process,
            state_store=state_store,
            run_id=run_id,
            input_payload=input_payload,
            cached_results=cached_results,
        )
