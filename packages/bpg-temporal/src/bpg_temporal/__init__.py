"""Public Temporal runtime surface for framework execution."""

from bpg_temporal.backend import TemporalExecutionBackend
from bpg_temporal.governance import (
    ApprovalRequiredPolicy,
    EscalationPolicy,
    GovernancePolicy,
    PolicyContext,
    PolicyEngine,
    PolicyViolation,
)
from bpg_temporal.hitl import (
    ActorIdentity,
    ApprovalGate,
    ApprovalOutcome,
    ApprovalRequest,
    ApprovalSignal,
    ApprovalState,
)
from bpg_temporal.metadata import (
    TemporalMetadata,
    enrich_event_with_temporal_metadata,
    enrich_run_event_with_temporal_metadata,
    extract_temporal_metadata,
)
from bpg_temporal.runtime import BpgWorkflow, LangGraphNodeWorkflow, TemporalRuntime

LEGACY_RUNTIME_MODULE = "bpg.runtime.engine"

__all__ = [
    "ActorIdentity",
    "ApprovalGate",
    "ApprovalOutcome",
    "ApprovalRequest",
    "ApprovalRequiredPolicy",
    "ApprovalSignal",
    "ApprovalState",
    "BpgWorkflow",
    "EscalationPolicy",
    "GovernancePolicy",
    "LangGraphNodeWorkflow",
    "LEGACY_RUNTIME_MODULE",
    "PolicyContext",
    "PolicyEngine",
    "PolicyViolation",
    "TemporalExecutionBackend",
    "TemporalMetadata",
    "TemporalRuntime",
    "enrich_event_with_temporal_metadata",
    "enrich_run_event_with_temporal_metadata",
    "extract_temporal_metadata",
]
