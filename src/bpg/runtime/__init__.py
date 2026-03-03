"""BPG runtime — event-driven process execution engine.

The runtime implements the node execution semantics defined in §7 of the spec:
    1. Wait  — block until all dependency nodes have completed or been skipped
    2. Evaluate — check all incoming ``when`` conditions
    3. Map  — assemble the input payload from ``with`` mappings
    4. Validate — assert input conforms to node's ``in`` type
    5. Invoke — call provider with input, config, and execution context
    6. Await — wait for provider output, subject to timeout
    7. Validate — assert output conforms to node's ``out`` type
    8. Persist — write result to execution log; mark node as ``completed``
"""

from bpg.runtime.engine import Engine, EngineError
from bpg.runtime.langgraph_runtime import LangGraphRuntime
from bpg.runtime.backends import available_backends, get_backend
from bpg.runtime.observability import (
    EventSink,
    ListEventSink,
    LoggingEventSink,
    NoopEventSink,
    RunEvent,
    replay_run,
)

__all__ = [
    "Engine",
    "EngineError",
    "LangGraphRuntime",
    "available_backends",
    "get_backend",
    "EventSink",
    "ListEventSink",
    "LoggingEventSink",
    "NoopEventSink",
    "RunEvent",
    "replay_run",
]
