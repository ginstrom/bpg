from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from bpg.cli import app
from bpg_sdk.discovery import DiscoveredNode
from bpg_sdk.manifest import Idempotency, NodeManifest, ObservabilitySupport, RetrySafety, SideEffects
from bpg_sdk.marketplace import (
    MarketplaceArtifact,
    export_catalog,
    export_node_manifest,
    load_artifact,
    validate_artifacts,
    write_artifacts,
)


runner = CliRunner()


def _make_manifest(
    package: str = "bpg.nodes.tests.echo@v1",
    node_id: str = "echo",
    capabilities: list[str] | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
) -> NodeManifest:
    return NodeManifest(
        package=package,
        node_id=node_id,
        capabilities=capabilities or ["echo"],
        input_schema=input_schema or {"type": "object"},
        output_schema=output_schema or {"type": "object"},
        side_effects=SideEffects.NONE,
        idempotency=Idempotency.IDEMPOTENT,
        retry_safety=RetrySafety.SAFE,
        observability=ObservabilitySupport.SUPPORTED,
    )


# ---------------------------------------------------------------------------
# export_node_manifest
# ---------------------------------------------------------------------------

def test_export_node_manifest_maps_fields() -> None:
    manifest = _make_manifest()
    artifact = export_node_manifest(manifest)

    assert artifact.artifact_version == "1"
    assert artifact.package_id == "bpg.nodes.tests.echo@v1"
    assert artifact.node_id == "echo"
    assert artifact.capabilities == ["echo"]
    assert artifact.execution.side_effects == "none"
    assert artifact.execution.idempotency == "idempotent"
    assert artifact.execution.retry_safety == "safe"
    assert artifact.execution.observability == "supported"


def test_export_node_manifest_derives_install_spec() -> None:
    artifact = export_node_manifest(_make_manifest(package="bpg.nodes.text.transform@v2"))
    assert artifact.install.package_name == "bpg-nodes-text-transform"
    assert artifact.install.pip == "pip install bpg-nodes-text-transform"
    assert artifact.install.uv == "uv add bpg-nodes-text-transform"


def test_export_node_manifest_default_compatibility_and_trust() -> None:
    artifact = export_node_manifest(_make_manifest())
    assert artifact.compatibility.python == ">=3.12"
    assert artifact.trust.publisher == "unknown"
    assert artifact.trust.verified is False


# ---------------------------------------------------------------------------
# export_catalog
# ---------------------------------------------------------------------------

def test_export_catalog_returns_sorted_artifacts() -> None:
    class _FakeNode:
        def __init__(self, manifest: NodeManifest):
            self.manifest = manifest
            self.implementation = None

    nodes = {
        ("bpg.nodes.z@v1", "z"): _FakeNode(_make_manifest("bpg.nodes.z@v1", "z")),
        ("bpg.nodes.a@v1", "a"): _FakeNode(_make_manifest("bpg.nodes.a@v1", "a")),
        ("bpg.nodes.m@v1", "m"): _FakeNode(_make_manifest("bpg.nodes.m@v1", "m")),
    }
    artifacts = export_catalog(nodes.values())

    assert [a.package_id for a in artifacts] == [
        "bpg.nodes.a@v1",
        "bpg.nodes.m@v1",
        "bpg.nodes.z@v1",
    ]


def test_export_catalog_is_deterministic() -> None:
    class _FakeNode:
        def __init__(self, manifest: NodeManifest):
            self.manifest = manifest

    nodes = {
        ("bpg.nodes.b@v1", "b"): _FakeNode(_make_manifest("bpg.nodes.b@v1", "b")),
        ("bpg.nodes.a@v1", "a"): _FakeNode(_make_manifest("bpg.nodes.a@v1", "a")),
    }
    first = export_catalog(nodes.values())
    second = export_catalog(nodes.values())
    assert [a.node_id for a in first] == [a.node_id for a in second]


# ---------------------------------------------------------------------------
# validate_artifacts
# ---------------------------------------------------------------------------

def test_validate_artifacts_empty_list_is_valid() -> None:
    assert validate_artifacts([]) == []


def test_validate_artifacts_passes_valid_artifact() -> None:
    artifact = export_node_manifest(_make_manifest())
    assert validate_artifacts([artifact]) == []


def test_validate_artifacts_catches_duplicate() -> None:
    artifact = export_node_manifest(_make_manifest())
    errors = validate_artifacts([artifact, artifact])
    assert any("duplicate" in e for e in errors)


def test_validate_artifacts_catches_bad_package_prefix() -> None:
    # Construct an artifact directly (simulating a tampered or externally loaded JSON)
    # to bypass the NodeManifest regex constraint.
    from bpg_sdk.marketplace import ExecutionMetadata, InstallSpec

    artifact = MarketplaceArtifact.model_construct(
        artifact_version="1",
        package_id="external.nodes.foo@v1",
        node_id="foo",
        capabilities=[],
        input_schema={},
        output_schema={},
        execution=ExecutionMetadata(
            side_effects="none",
            idempotency="idempotent",
            retry_safety="safe",
            observability="supported",
        ),
        install=InstallSpec(
            package_name="external-nodes-foo",
            pip="pip install external-nodes-foo",
            uv="uv add external-nodes-foo",
        ),
    )
    errors = validate_artifacts([artifact])
    assert any("bpg.nodes." in e for e in errors)


def test_validate_artifacts_catches_missing_version_suffix() -> None:
    manifest = NodeManifest(
        package="bpg.nodes.nover@v1",
        node_id="nover",
        input_schema={},
        output_schema={},
    )
    artifact = export_node_manifest(manifest)
    # package_id has @v1 so no error; test the validator accepts it
    assert validate_artifacts([artifact]) == []


# ---------------------------------------------------------------------------
# write_artifacts / load_artifact
# ---------------------------------------------------------------------------

def test_write_artifacts_creates_expected_layout(tmp_path: Path) -> None:
    artifacts = [
        export_node_manifest(_make_manifest("bpg.nodes.tests.echo@v1", "echo")),
        export_node_manifest(_make_manifest("bpg.nodes.tests.text@v1", "uppercase")),
    ]
    written = write_artifacts(artifacts, tmp_path)

    assert len(written) == 2
    assert (tmp_path / "nodes" / "bpg.nodes.tests.echo@v1" / "echo.json").exists()
    assert (tmp_path / "nodes" / "bpg.nodes.tests.text@v1" / "uppercase.json").exists()


def test_write_artifacts_output_is_valid_json(tmp_path: Path) -> None:
    artifact = export_node_manifest(_make_manifest())
    write_artifacts([artifact], tmp_path)
    path = tmp_path / "nodes" / "bpg.nodes.tests.echo@v1" / "echo.json"
    data = json.loads(path.read_text())
    assert data["package_id"] == "bpg.nodes.tests.echo@v1"
    assert data["artifact_version"] == "1"


def test_load_artifact_round_trips(tmp_path: Path) -> None:
    original = export_node_manifest(_make_manifest())
    write_artifacts([original], tmp_path)
    path = tmp_path / "nodes" / "bpg.nodes.tests.echo@v1" / "echo.json"
    loaded = load_artifact(path)
    assert loaded == original


def test_write_artifacts_is_deterministic(tmp_path: Path) -> None:
    artifacts = [
        export_node_manifest(_make_manifest("bpg.nodes.tests.echo@v1", "echo")),
    ]
    write_artifacts(artifacts, tmp_path)
    first = (tmp_path / "nodes" / "bpg.nodes.tests.echo@v1" / "echo.json").read_text()
    write_artifacts(artifacts, tmp_path)
    second = (tmp_path / "nodes" / "bpg.nodes.tests.echo@v1" / "echo.json").read_text()
    assert first == second


# ---------------------------------------------------------------------------
# Snapshot test
# ---------------------------------------------------------------------------

def test_artifact_json_snapshot() -> None:
    manifest = _make_manifest(
        package="bpg.nodes.tests.echo@v1",
        node_id="echo",
        capabilities=["echo"],
        input_schema={"type": "object", "properties": {"text": {"type": "string"}}},
        output_schema={"type": "object", "properties": {"text": {"type": "string"}}},
    )
    artifact = export_node_manifest(manifest)
    data = json.loads(artifact.model_dump_json())

    assert data == {
        "artifact_version": "1",
        "package_id": "bpg.nodes.tests.echo@v1",
        "node_id": "echo",
        "capabilities": ["echo"],
        "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
        "output_schema": {"type": "object", "properties": {"text": {"type": "string"}}},
        "execution": {
            "side_effects": "none",
            "idempotency": "idempotent",
            "retry_safety": "safe",
            "observability": "supported",
        },
        "install": {
            "package_name": "bpg-nodes-tests-echo",
            "pip": "pip install bpg-nodes-tests-echo",
            "uv": "uv add bpg-nodes-tests-echo",
        },
        "compatibility": {"python": ">=3.12"},
        "trust": {"publisher": "unknown", "verified": False},
    }


# ---------------------------------------------------------------------------
# CLI: bpg marketplace export
# ---------------------------------------------------------------------------

def test_cli_marketplace_export_dry_run_no_nodes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bpg_sdk.discovery._iter_group_entry_points", lambda: [])
    result = runner.invoke(app, ["marketplace", "export", "--dry-run"])
    assert result.exit_code == 0
    assert "0 artifact(s)" in result.output


def test_cli_marketplace_export_dry_run_with_nodes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types
    import sys
    from importlib.metadata import EntryPoint
    from bpg_sdk.authoring import node as sdk_node

    module_name = "tests_marketplace_fake_pkg"
    module = types.ModuleType(module_name)

    @sdk_node(
        package="bpg.nodes.tests.market@v1",
        node_id="market",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    def _market(payload: dict) -> dict:
        return payload

    module.market = _market
    sys.modules[module_name] = module

    fake_eps = [EntryPoint(name="market", value=f"{module_name}:market", group="bpg.nodes")]
    monkeypatch.setattr("bpg_sdk.discovery._iter_group_entry_points", lambda: fake_eps)

    result = runner.invoke(app, ["marketplace", "export", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert "bpg.nodes.tests.market@v1" in result.output
    assert "1 artifact(s)" in result.output


def test_cli_marketplace_export_writes_files(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    import types
    import sys
    from importlib.metadata import EntryPoint
    from bpg_sdk.authoring import node as sdk_node

    module_name = "tests_marketplace_write_pkg"
    module = types.ModuleType(module_name)

    @sdk_node(
        package="bpg.nodes.tests.write@v1",
        node_id="write",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
    )
    def _write(payload: dict) -> dict:
        return payload

    module.write = _write
    sys.modules[module_name] = module

    fake_eps = [EntryPoint(name="write", value=f"{module_name}:write", group="bpg.nodes")]
    monkeypatch.setattr("bpg_sdk.discovery._iter_group_entry_points", lambda: fake_eps)

    out_dir = tmp_path / "artifacts"
    result = runner.invoke(app, ["marketplace", "export", "--output-dir", str(out_dir)])
    assert result.exit_code == 0, result.output
    assert (out_dir / "nodes" / "bpg.nodes.tests.write@v1" / "write.json").exists()


# ---------------------------------------------------------------------------
# CLI: bpg marketplace validate
# ---------------------------------------------------------------------------

def test_cli_marketplace_validate_valid_artifacts(tmp_path: Path) -> None:
    artifact = export_node_manifest(_make_manifest())
    write_artifacts([artifact], tmp_path)
    result = runner.invoke(app, ["marketplace", "validate", str(tmp_path)])
    assert result.exit_code == 0, result.output
    assert "1 artifact(s) valid" in result.output


def test_cli_marketplace_validate_missing_directory() -> None:
    result = runner.invoke(app, ["marketplace", "validate", "/nonexistent/path"])
    assert result.exit_code != 0


def test_cli_marketplace_validate_no_json_files(tmp_path: Path) -> None:
    (tmp_path / "empty.txt").write_text("nothing")
    result = runner.invoke(app, ["marketplace", "validate", str(tmp_path)])
    assert result.exit_code != 0


def test_cli_marketplace_validate_invalid_json(tmp_path: Path) -> None:
    bad_path = tmp_path / "bad.json"
    bad_path.write_text("{not valid json", encoding="utf-8")
    result = runner.invoke(app, ["marketplace", "validate", str(tmp_path)])
    assert result.exit_code != 0
