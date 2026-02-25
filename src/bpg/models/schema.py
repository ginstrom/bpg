"""Pydantic models for BPG core domain concepts.

These models reflect the BPG specification (v0.2) and are used throughout the
compiler, runtime, and state layers.  All models are immutable by default to
enforce the spec's "types are immutable once published" guarantee.

Reference: docs/bpg-spec.md
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Shared configuration
# ---------------------------------------------------------------------------

class _ImmutableModel(BaseModel):
    """Base model that forbids mutation and ignores extra fields from YAML."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Types (§3.1)
# ---------------------------------------------------------------------------

class TypeDef(_ImmutableModel):
    """A named, structured type registered in the global type registry.

    Field values are BPG primitive type strings, e.g. "string", "bool",
    "enum(S1,S2,S3)", "list<string>", or optional variants ending with "?".

    Example:
        BugReport:
          title: string
          severity: enum(S1,S2,S3)
          description: string
          reporter_email: string?
    """

    name: str = Field(description="Registered type name, e.g. 'BugReport'.")
    fields: Dict[str, str] = Field(
        description=(
            "Mapping of field name to BPG type string. "
            "Optional fields are denoted with a trailing '?'."
        )
    )


# ---------------------------------------------------------------------------
# Node Types (§3.2)
# ---------------------------------------------------------------------------

class NodeType(_ImmutableModel):
    """A versioned, reusable execution component definition.

    Declares the interface contract (input type, output type) and provider
    binding for a class of work.  Node types are referenced by node instances
    as ``<name>@<version>``.

    Example:
        triage_agent@v1:
          in: BugReport
          out: TriageResult
          provider: agent.pipeline
          version: v1
          config_schema:
            pipeline: string
            model: string?
    """

    name: str = Field(description="Node type name, e.g. 'triage_agent'.")
    version: str = Field(description="Semantic version string, e.g. 'v1'.")
    input_type: str = Field(alias="in", description="Name of the registered input TypeDef.")
    output_type: str = Field(alias="out", description="Name of the registered output TypeDef.")
    provider: str = Field(description="Provider identifier, e.g. 'agent.pipeline'.")
    config_schema: Dict[str, str] = Field(
        default_factory=dict,
        description="Schema for node instance configuration values.",
    )
    description: Optional[str] = Field(default=None)
    timeout_default: Optional[str] = Field(
        default=None,
        description="Default execution timeout, e.g. '5m' or '24h'.",
    )

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @property
    def qualified_name(self) -> str:
        """Return the versioned node type identifier, e.g. 'triage_agent@v1'."""
        return f"{self.name}@{self.version}"


# ---------------------------------------------------------------------------
# Retry Policy (§10)
# ---------------------------------------------------------------------------

class BackoffStrategy(str, Enum):
    """Supported retry backoff strategies."""

    LINEAR = "linear"
    EXPONENTIAL = "exponential"
    CONSTANT = "constant"


class RetryPolicy(_ImmutableModel):
    """Node-level retry configuration.

    Example:
        retry:
          max_attempts: 3
          backoff: exponential
          initial_delay: 5s
          max_delay: 60s
    """

    max_attempts: int = Field(ge=1, description="Maximum number of invocation attempts.")
    backoff: BackoffStrategy = Field(default=BackoffStrategy.EXPONENTIAL)
    initial_delay: Optional[str] = Field(
        default=None,
        description="Initial retry delay as a duration string, e.g. '5s'.",
    )
    max_delay: Optional[str] = Field(
        default=None,
        description="Maximum retry delay as a duration string, e.g. '60s'.",
    )
    retryable_errors: List[str] = Field(
        default_factory=list,
        description="List of provider error codes that should trigger a retry.",
    )


# ---------------------------------------------------------------------------
# Node Instances (§4.1)
# ---------------------------------------------------------------------------

class NodeInstance(_ImmutableModel):
    """A configured deployment of a NodeType within a specific process.

    Instances bind a node type to concrete configuration values.  They MUST
    NOT override the ``in`` or ``out`` type declared by their node type.

    Example:
        triage:
          type: triage_agent@v1
          config:
            pipeline: triage_v2
            model: gpt-4o
    """

    name: str = Field(description="Instance name within the process, e.g. 'triage'.")
    node_type: str = Field(
        alias="type",
        description="Versioned node type reference, e.g. 'triage_agent@v1'.",
    )
    config: Dict[str, Any] = Field(
        default_factory=dict,
        description="Concrete configuration values matching the node type's config_schema.",
    )
    description: Optional[str] = Field(default=None)
    retry: Optional[RetryPolicy] = Field(default=None)
    on_timeout: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Synthetic output emitted when a human node times out.",
    )

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Edges (§4.2)
# ---------------------------------------------------------------------------

class EdgeFailureAction(str, Enum):
    """Actions available when a target node fails."""

    ROUTE = "route"
    NOTIFY = "notify"
    FAIL = "fail"


class EdgeOnFailure(_ImmutableModel):
    """Failure routing configuration attached to an edge."""

    action: EdgeFailureAction
    to: Optional[str] = Field(
        default=None,
        description="Target node name to route to on failure (used with action=route).",
    )
    node: Optional[str] = Field(
        default=None,
        description="Notification node name (used with action=notify).",
    )


class Edge(_ImmutableModel):
    """A directed conditional relationship between two node instances.

    Edges define execution dependencies and optional data mappings.  The
    ``when`` expression, if present, must be satisfied for the edge to fire.

    Example:
        - from: triage
          to: approval
          when: 'triage.out.risk == "high"'
          with:
            title: "High-risk bug: {{triage.out.summary}}"
            risk_level: triage.out.risk
    """

    source: str = Field(alias="from", description="Source node instance name.")
    target: str = Field(alias="to", description="Target node instance name.")
    when: Optional[str] = Field(
        default=None,
        description="Boolean condition expression; edge fires unconditionally if omitted.",
    )
    mapping: Optional[Dict[str, str]] = Field(
        alias="with",
        default=None,
        description="Data mapping from source outputs to target inputs.",
    )
    timeout: Optional[str] = Field(
        default=None,
        description="Per-edge timeout override.",
    )
    on_failure: Optional[EdgeOnFailure] = Field(default=None)

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Node execution status (§7)
# ---------------------------------------------------------------------------

class NodeStatus(str, Enum):
    """Execution status of a node instance within a process run."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# Process (§4)
# ---------------------------------------------------------------------------

class ProcessMetadata(_ImmutableModel):
    """Human-readable metadata attached to a process definition."""

    name: str
    version: str
    description: Optional[str] = None
    owner: Optional[str] = None


class Process(_ImmutableModel):
    """A complete, deployable BPG process definition.

    Parsed from a ``process.bpg.yaml`` file.  A process MUST contain nodes,
    edges, and a trigger declaration.

    Example:
        metadata:
          name: bug-triage-process
          version: 1.4.0
        nodes: { ... }
        edges: [ ... ]
        trigger: intake_form
        output: gitlab.out.ticket_id
    """

    metadata: Optional[ProcessMetadata] = None
    types: Dict[str, TypeDef] = Field(
        default_factory=dict,
        description="Type definitions declared inline in the process file.",
    )
    node_types: Dict[str, NodeType] = Field(
        default_factory=dict,
        description="Node type definitions declared inline in the process file.",
    )
    nodes: Dict[str, NodeInstance] = Field(
        description="Node instances keyed by instance name.",
    )
    edges: List[Edge] = Field(
        description="Directed edges forming the execution graph.",
    )
    trigger: str = Field(
        description="Name of the node instance that serves as the process entry point.",
    )
    output: Optional[str] = Field(
        default=None,
        description="Field reference for the process return value, e.g. 'gitlab.out.ticket_id'.",
    )
    policy: Optional[Dict[str, Any]] = Field(default=None)
