"""Compiler support for framework process spec v2."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
from typing import Any, Mapping

from bpg.models.schema import (
    ApprovalPolicyV2,
    CompensationPolicyV2,
    ObservabilityPolicyV2,
    ProcessEdgeSpecV2,
    ProcessSpecV2,
    RetryPolicy,
)
from bpg.compiler.validator import ValidationError


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


def _topologically_sorted_node_ids(spec: ProcessSpecV2) -> list[str]:
    """Return a deterministic topological ordering for process nodes."""
    nodes = spec.process.nodes
    adjacency: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree = {node_id: 0 for node_id in nodes}

    for edge in spec.process.edges:
        adjacency[edge.source].append(edge.target)
        indegree[edge.target] += 1

    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    heapq.heapify(ready)

    ordered: list[str] = []
    while ready:
        node_id = heapq.heappop(ready)
        ordered.append(node_id)
        for target in sorted(adjacency[node_id]):
            indegree[target] -= 1
            if indegree[target] == 0:
                heapq.heappush(ready, target)

    if len(ordered) != len(nodes):
        raise ValidationError(
            f"Cycle detected in process {spec.process.name!r}",
            field="process.edges",
            path="$.process.edges",
            code="E_GRAPH_CYCLE",
        )

    return ordered


def validate_process_spec_v2(
    spec: ProcessSpecV2,
    *,
    node_catalog: Mapping[tuple[str, str], Any] | None = None,
) -> None:
    """Validate graph shape and framework-owned semantics for process spec v2."""
    nodes = spec.process.nodes
    if spec.process.trigger not in nodes:
        raise ValidationError(
            f"Unknown trigger node {spec.process.trigger!r}",
            field="process.trigger",
            path="$.process.trigger",
            code="E_TRIGGER_UNKNOWN",
        )

    incoming_to_trigger = []
    for edge_index, edge in enumerate(spec.process.edges):
        if edge.source not in nodes:
            raise ValidationError(
                f"Unknown edge source {edge.source!r}",
                field="process.edges",
                path=f"$.process.edges[{edge_index}].from",
                code="E_EDGE_SOURCE_UNKNOWN",
            )
        if edge.target not in nodes:
            raise ValidationError(
                f"Unknown edge target {edge.target!r}",
                field="process.edges",
                path=f"$.process.edges[{edge_index}].to",
                code="E_EDGE_TARGET_UNKNOWN",
            )
        if edge.target == spec.process.trigger:
            incoming_to_trigger.append(edge_index)

    if incoming_to_trigger:
        raise ValidationError(
            f"Trigger node {spec.process.trigger!r} must not have incoming edges",
            field="process.trigger",
            path="$.process.trigger",
            code="E_TRIGGER_INCOMING_EDGE",
        )

    for node_id, node in nodes.items():
        if node_catalog is not None and (node.ref.package, node.ref.node) not in node_catalog:
            raise ValidationError(
                f"Node {node_id!r} references undiscovered package export "
                f"{node.ref.package}:{node.ref.node}",
                node=node_id,
                field="process.nodes",
                path=f"$.process.nodes.{node_id}.ref",
                code="E_NODE_REF_UNDISCOVERED",
            )
        compensation = node.compensation
        if compensation and compensation.strategy == "run_node":
            if not compensation.node:
                raise ValidationError(
                    f"Node {node_id!r} requires a compensation.node target",
                    node=node_id,
                    field="process.nodes",
                    path=f"$.process.nodes.{node_id}.compensation.node",
                    code="E_COMPENSATION_TARGET_REQUIRED",
                )
            if compensation.node not in nodes:
                raise ValidationError(
                    f"Node {node_id!r} references unknown compensation target {compensation.node!r}",
                    node=node_id,
                    field="process.nodes",
                    path=f"$.process.nodes.{node_id}.compensation.node",
                    code="E_COMPENSATION_TARGET_UNKNOWN",
                )

    _topologically_sorted_node_ids(spec)


def compile_process_spec_v2(
    spec: ProcessSpecV2,
    *,
    node_catalog: Mapping[tuple[str, str], Any] | None = None,
) -> CompiledProcessSpecV2:
    """Compile process spec v2 into execution and capability IR."""
    validate_process_spec_v2(spec, node_catalog=node_catalog)

    sorted_node_ids = _topologically_sorted_node_ids(spec)
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
        edges=tuple(
            sorted(
                spec.process.edges,
                key=lambda edge: (edge.source, edge.target, edge.when or ""),
            )
        ),
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
