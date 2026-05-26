"""Compiler support for framework process spec v2."""

from __future__ import annotations

from dataclasses import dataclass

from bpg.models.schema import (
    ApprovalPolicyV2,
    CompensationPolicyV2,
    ObservabilityPolicyV2,
    ProcessEdgeSpecV2,
    ProcessSpecV2,
    RetryPolicy,
)


@dataclass(frozen=True)
class NodeExecutionPlanV2:
    """Temporal-ready node execution plan derived from process spec v2."""

    node_id: str
    package_id: str
    package_node_id: str
    config: dict[str, object]
    retry: RetryPolicy | None
    timeout: str | None
    approval: ApprovalPolicyV2 | None
    compensation: CompensationPolicyV2 | None
    observability: ObservabilityPolicyV2 | None


@dataclass(frozen=True)
class ProcessExecutionPlanV2:
    """Canonical execution plan emitted by the v2 compiler."""

    process_name: str
    trigger: str
    nodes: tuple[NodeExecutionPlanV2, ...]
    edges: tuple[ProcessEdgeSpecV2, ...]


@dataclass(frozen=True)
class CapabilityRequirementsSummary:
    """Capability requirements summary for runtime bootstrapping and policy checks."""

    required_packages: list[str]
    approval_nodes: list[str]
    compensation_nodes: list[str]
    observability_nodes: list[str]


@dataclass(frozen=True)
class CompiledProcessSpecV2:
    """Complete v2 compiler output."""

    execution_plan: ProcessExecutionPlanV2
    capability_requirements: CapabilityRequirementsSummary


def validate_process_spec_v2(spec: ProcessSpecV2) -> None:
    """Validate graph shape and framework-owned semantics for process spec v2."""
    nodes = spec.process.nodes
    if spec.process.trigger not in nodes:
        raise ValueError(f"Unknown trigger node {spec.process.trigger!r}")

    for edge in spec.process.edges:
        if edge.source not in nodes:
            raise ValueError(f"Unknown edge source {edge.source!r}")
        if edge.target not in nodes:
            raise ValueError(f"Unknown edge target {edge.target!r}")

    for node_id, node in nodes.items():
        compensation = node.compensation
        if compensation and compensation.strategy == "run_node":
            if not compensation.node:
                raise ValueError(f"Node {node_id!r} requires a compensation.node target")
            if compensation.node not in nodes:
                raise ValueError(
                    f"Node {node_id!r} references unknown compensation target {compensation.node!r}"
                )


def compile_process_spec_v2(spec: ProcessSpecV2) -> CompiledProcessSpecV2:
    """Compile process spec v2 into execution and capability IR."""
    validate_process_spec_v2(spec)

    sorted_node_ids = list(spec.process.nodes)
    plan_nodes = tuple(
        NodeExecutionPlanV2(
            node_id=node_id,
            package_id=spec.process.nodes[node_id].ref.package,
            package_node_id=spec.process.nodes[node_id].ref.node,
            config=dict(spec.process.nodes[node_id].config),
            retry=spec.process.nodes[node_id].retry,
            timeout=spec.process.nodes[node_id].timeout,
            approval=spec.process.nodes[node_id].approval,
            compensation=spec.process.nodes[node_id].compensation,
            observability=spec.process.nodes[node_id].observability,
        )
        for node_id in sorted_node_ids
    )

    execution_plan = ProcessExecutionPlanV2(
        process_name=spec.process.name,
        trigger=spec.process.trigger,
        nodes=plan_nodes,
        edges=tuple(spec.process.edges),
    )

    capability_requirements = CapabilityRequirementsSummary(
        required_packages=sorted({node.package_id for node in plan_nodes}),
        approval_nodes=sorted(
            node.node_id for node in plan_nodes if node.approval and node.approval.required
        ),
        compensation_nodes=sorted(
            node.node_id
            for node in plan_nodes
            if node.compensation and node.compensation.strategy != "none"
        ),
        observability_nodes=sorted(node.node_id for node in plan_nodes if node.observability),
    )
    return CompiledProcessSpecV2(
        execution_plan=execution_plan,
        capability_requirements=capability_requirements,
    )
