"""LangGraph RunState definition for BPG process execution.

RunState is the shared state dict that flows through a LangGraph StateGraph.
Reducer annotations on node_outputs, node_statuses, and execution_log allow
each node function to return partial updates that are merged into the running
state without overwriting unrelated keys.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, Dict, List

from typing_extensions import TypedDict


def _merge_dicts(left: Dict, right: Dict) -> Dict:
    """Merge two dicts, letting right overwrite left for shared keys."""
    return {**left, **right}


class RunState(TypedDict):
    """Mutable execution state for a single BPG process run."""

    run_id: str
    process_name: str
    trigger_input: Dict[str, Any]
    node_outputs: Annotated[Dict[str, Dict[str, Any]], _merge_dicts]
    node_statuses: Annotated[Dict[str, str], _merge_dicts]
    execution_log: Annotated[List[Dict[str, Any]], operator.add]
    failure_routes: Annotated[Dict[str, Dict[str, Any]], _merge_dicts]
    recoverable_failures: Annotated[List[str], operator.add]
    run_status: str
