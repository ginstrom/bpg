"""Public Temporal runtime surface for framework execution."""

from bpg_temporal.backend import TemporalExecutionBackend
from bpg_temporal.runtime import BpgWorkflow, TemporalRuntime

LEGACY_RUNTIME_MODULE = "bpg.runtime.engine"

__all__ = [
    "BpgWorkflow",
    "LEGACY_RUNTIME_MODULE",
    "TemporalExecutionBackend",
    "TemporalRuntime",
]
