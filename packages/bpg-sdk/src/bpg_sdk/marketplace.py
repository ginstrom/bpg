from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Iterable, Literal

from pydantic import BaseModel, ConfigDict, Field

from bpg_sdk.manifest import NodeManifest

if TYPE_CHECKING:
    from bpg_sdk.discovery import DiscoveredNode


ARTIFACT_SCHEMA_VERSION: Literal["1"] = "1"


class ExecutionMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)
    side_effects: str
    idempotency: str
    retry_safety: str
    observability: str


class InstallSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    package_name: str
    pip: str
    uv: str


class CompatibilitySpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    python: str = ">=3.12"


class TrustMetadata(BaseModel):
    model_config = ConfigDict(frozen=True)
    publisher: str = "unknown"
    verified: bool = False


class MarketplaceArtifact(BaseModel):
    model_config = ConfigDict(frozen=True)
    artifact_version: Literal["1"] = ARTIFACT_SCHEMA_VERSION
    package_id: str
    node_id: str
    capabilities: list[str]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    execution: ExecutionMetadata
    install: InstallSpec
    compatibility: CompatibilitySpec = Field(default_factory=CompatibilitySpec)
    trust: TrustMetadata = Field(default_factory=TrustMetadata)


def _derive_package_name(package_id: str) -> str:
    """Derive an installable package name from a node package_id.

    Examples:
        bpg.nodes.echo@v1 -> bpg-nodes-echo
        bpg.nodes.text.transform@v2 -> bpg-nodes-text-transform
    """
    base = package_id.split("@")[0]
    return base.replace(".", "-")


def export_node_manifest(manifest: NodeManifest) -> MarketplaceArtifact:
    """Map a single NodeManifest to a MarketplaceArtifact."""
    package_name = _derive_package_name(manifest.package)
    return MarketplaceArtifact(
        package_id=manifest.package,
        node_id=manifest.node_id,
        capabilities=list(manifest.capabilities),
        input_schema=dict(manifest.input_schema),
        output_schema=dict(manifest.output_schema),
        execution=ExecutionMetadata(
            side_effects=manifest.side_effects.value,
            idempotency=manifest.idempotency.value,
            retry_safety=manifest.retry_safety.value,
            observability=manifest.observability.value,
        ),
        install=InstallSpec(
            package_name=package_name,
            pip=f"pip install {package_name}",
            uv=f"uv add {package_name}",
        ),
    )


def export_catalog(nodes: Iterable[DiscoveredNode]) -> list[MarketplaceArtifact]:
    """Export discovered nodes as a deterministically ordered list of marketplace artifacts."""
    artifacts = [export_node_manifest(n.manifest) for n in nodes]
    return sorted(artifacts, key=lambda a: (a.package_id, a.node_id))


def validate_artifacts(artifacts: list[MarketplaceArtifact]) -> list[str]:
    """Domain-level validation on top of Pydantic schema enforcement.

    Returns a list of error messages; an empty list means all artifacts are valid.
    """
    errors: list[str] = []
    seen: set[tuple[str, str]] = set()
    for artifact in artifacts:
        key = (artifact.package_id, artifact.node_id)
        if key in seen:
            errors.append(f"duplicate artifact: {artifact.package_id}:{artifact.node_id}")
        seen.add(key)
        if not artifact.package_id.startswith("bpg.nodes."):
            errors.append(
                f"{artifact.package_id}:{artifact.node_id}: "
                "package_id must start with 'bpg.nodes.'"
            )
        if "@" not in artifact.package_id:
            errors.append(
                f"{artifact.package_id}:{artifact.node_id}: "
                "package_id must include a version suffix (e.g. @v1)"
            )
    return errors


def load_artifact(path: Path) -> MarketplaceArtifact:
    """Load and validate a marketplace artifact from a JSON file."""
    return MarketplaceArtifact.model_validate_json(path.read_text(encoding="utf-8"))


def write_artifacts(artifacts: list[MarketplaceArtifact], output_dir: Path) -> list[Path]:
    """Write artifacts to the marketplace artifact layout.

    Layout::

        <output_dir>/nodes/<package_id>/<node_id>.json

    Returns sorted list of written paths.
    """
    written: list[Path] = []
    for artifact in sorted(artifacts, key=lambda a: (a.package_id, a.node_id)):
        pkg_dir = output_dir / "nodes" / artifact.package_id
        pkg_dir.mkdir(parents=True, exist_ok=True)
        path = pkg_dir / f"{artifact.node_id}.json"
        path.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")
        written.append(path)
    return written
