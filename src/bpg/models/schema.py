"""Pydantic models for BPG core domain concepts.

These models reflect the BPG specification (v0.2) and are used throughout the
compiler, runtime, and state layers.  All models are immutable by default to
enforce the spec's "types are immutable once published" guarantee.

Reference: docs/bpg-spec.md
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, RootModel


# ---------------------------------------------------------------------------
# Shared configuration
# ---------------------------------------------------------------------------

class _ImmutableModel(BaseModel):
    """Base model that forbids mutation and ignores extra fields from YAML."""

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Types (§3.1)
# ---------------------------------------------------------------------------

class TypeDef(RootModel):
    """A structured type definition (mapping of field name to BPG type string).

    Example:
        BugReport:
          title: string
          severity: enum(S1,S2,S3)
    """

    root: Dict[str, str]

    def __getitem__(self, item: str) -> str:
        return self.root[item]

    def items(self):
        return self.root.items()


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

    input_type: str = Field(alias="in", description="Name of the registered input TypeDef.")
    output_type: str = Field(alias="out", description="Name of the registered output TypeDef.")
    provider: str = Field(description="Provider identifier, e.g. 'agent.pipeline'.")
    version: str = Field(description="Semantic version string.")
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
    stable_input_fields: Optional[List[str]] = Field(
        default=None,
        description="Top-level input fields to include in idempotency key computation.",
    )
    unstable_input_fields: Optional[List[str]] = Field(
        default=None,
        description="Top-level input fields to exclude from idempotency key computation.",
    )
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
    mapping: Optional[Dict[str, Any]] = Field(
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
# Modules (§12)
# ---------------------------------------------------------------------------

class ModuleDefinition(_ImmutableModel):
    """A reusable process fragment.

    Modules define named input parameters, internal node instances, internal
    edges, and exported outputs. They are referenced in processes as a
    node instance type.

    Example:
        risk_routing@v1:
          description: "Routes a triage result to either approval or direct filing."
          inputs:
            triage_result: TriageResult
            reporter_email: string
          nodes:
            approval: { ... }
            gitlab: { ... }
          edges:
            - from: __input__
              to: approval
              when: triage_result.risk == "high"
          outputs:
            ticket_id: gitlab.out.ticket_id
          version: v1
    """

    description: Optional[str] = Field(default=None)
    inputs: Dict[str, str] = Field(
        description="Named input parameters and their BPG types.",
    )
    nodes: Dict[str, NodeInstance] = Field(
        description="Internal node instances scoped to the module.",
    )
    edges: List[Edge] = Field(
        description="Internal edges forming the module's execution graph.",
    )
    outputs: Dict[str, str] = Field(
        description="Exported output mappings (name to internal field reference).",
    )
    version: str = Field(description="Semantic version string.")

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)


# ---------------------------------------------------------------------------
# Security & Policy (§13)
# ---------------------------------------------------------------------------

class AccessControlPolicy(_ImmutableModel):
    """Restrict who may act on a human node."""

    node: str
    allowed_roles: List[str]


class PIIRedactionPolicy(_ImmutableModel):
    """Redact specified fields in execution logs."""

    node: str
    redact_fields: List[str]


class AuditPolicy(_ImmutableModel):
    """Log retention and export settings."""

    retain_run_logs_for: Optional[str] = None
    export_to: Optional[str] = None
    tags: Optional[Dict[str, str]] = None


class Policy(_ImmutableModel):
    """Process-level security and governance configuration."""

    access_control: Optional[List[AccessControlPolicy]] = None
    separation_of_duties: Optional[Dict[str, Any]] = None
    pii_redaction: Optional[List[PIIRedactionPolicy]] = None
    audit: Optional[AuditPolicy] = None
    escalation: Optional[List[Dict[Any, Any]]] = None


class ArtifactFormat(str, Enum):
    """Supported output artifact serialization formats."""

    JSON = "json"
    JSONL = "jsonl"
    CSV = "csv"


class ArtifactSpec(_ImmutableModel):
    """Process-level output artifact declaration.

    Example:
        artifacts:
          - name: enriched_items
            from: enrich.out.items
            format: jsonl
    """

    name: str
    from_ref: str = Field(alias="from")
    format: ArtifactFormat = Field(default=ArtifactFormat.JSON)
    path: Optional[str] = None

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
    imports: List[str] = Field(
        default_factory=list,
        description="Relative file paths providing shared types/node_types/modules.",
    )
    types: Dict[str, TypeDef] = Field(
        default_factory=dict,
        description="Type definitions declared inline in the process file.",
    )
    node_types: Dict[str, NodeType] = Field(
        default_factory=dict,
        description="Node type definitions declared inline in the process file.",
    )
    modules: Dict[str, ModuleDefinition] = Field(
        default_factory=dict,
        description="Module definitions declared inline in the process file.",
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
    artifacts: List[ArtifactSpec] = Field(
        default_factory=list,
        description="Optional declared output artifacts materialized at run completion.",
    )
    policy: Optional[Policy] = Field(default=None)
