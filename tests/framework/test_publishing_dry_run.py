"""Verify all workspace packages are correctly configured for publishing (step 09)."""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]

FRAMEWORK_PACKAGES = [
    "bpg-core",
    "bpg-sdk",
    "bpg-temporal",
    "bpg-langgraph",
    "bpg-cli",
]
NODE_PACKAGES = [
    "bpg-nodes-core",
    "bpg-nodes-ai",
    "bpg-nodes-human",
    "bpg-nodes-search",
    "bpg-nodes-comm",
]
ALL_PACKAGES = FRAMEWORK_PACKAGES + NODE_PACKAGES


def _load_pyproject(package_name: str) -> dict:
    path = REPO_ROOT / "packages" / package_name / "pyproject.toml"
    return tomllib.loads(path.read_text())


@pytest.mark.parametrize("package_name", ALL_PACKAGES)
def test_package_has_required_project_fields(package_name: str) -> None:
    pyproject = _load_pyproject(package_name)
    project = pyproject["project"]
    assert project["name"] == package_name
    assert "version" in project
    assert "description" in project
    assert "requires-python" in project


@pytest.mark.parametrize("package_name", ALL_PACKAGES)
def test_package_has_uv_build_system(package_name: str) -> None:
    pyproject = _load_pyproject(package_name)
    build = pyproject["build-system"]
    assert "requires" in build
    assert "build-backend" in build
    assert build["build-backend"] == "uv_build"


def test_all_packages_at_same_version() -> None:
    versions = {pkg: _load_pyproject(pkg)["project"]["version"] for pkg in ALL_PACKAGES}
    unique = set(versions.values())
    assert len(unique) == 1, f"Package versions differ: {versions}"


def test_framework_packages_version_matches_root() -> None:
    root = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text())
    root_version = root["project"]["version"]
    for package_name in FRAMEWORK_PACKAGES:
        pkg_version = _load_pyproject(package_name)["project"]["version"]
        assert pkg_version == root_version, (
            f"{package_name} version {pkg_version!r} != root {root_version!r}"
        )


@pytest.mark.parametrize("package_name", NODE_PACKAGES)
def test_node_package_has_bpg_nodes_entry_points(package_name: str) -> None:
    pyproject = _load_pyproject(package_name)
    entry_points = pyproject.get("project", {}).get("entry-points", {})
    assert "bpg.nodes" in entry_points, (
        f"{package_name} is missing [project.entry-points.\"bpg.nodes\"]"
    )
    assert len(entry_points["bpg.nodes"]) > 0, (
        f"{package_name} has empty bpg.nodes entry points"
    )


def test_bpg_cli_has_bpg_script_entrypoint() -> None:
    pyproject = _load_pyproject("bpg-cli")
    scripts = pyproject.get("project", {}).get("scripts", {})
    assert "bpg" in scripts, "bpg-cli is missing the 'bpg' script entrypoint"


def test_bpg_cli_script_points_to_bpg_cli() -> None:
    pyproject = _load_pyproject("bpg-cli")
    scripts = pyproject["project"]["scripts"]
    entrypoint = scripts["bpg"]
    assert entrypoint.startswith("bpg_cli"), (
        f"bpg script should point to bpg_cli module, got: {entrypoint!r}"
    )


def test_bpg_cli_declares_sdk_dependency() -> None:
    pyproject = _load_pyproject("bpg-cli")
    deps = pyproject.get("project", {}).get("dependencies", [])
    dep_names = [d.split(">=")[0].split("==")[0].strip() for d in deps]
    assert "bpg-sdk" in dep_names, "bpg-cli should declare bpg-sdk as a dependency"
