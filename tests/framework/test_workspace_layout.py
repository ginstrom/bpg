from __future__ import annotations

import shlex
import shutil
import subprocess
import tomllib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_WORKSPACE_MEMBERS = [
    "packages/bpg-core",
    "packages/bpg-sdk",
    "packages/bpg-temporal",
    "packages/bpg-langgraph",
    "packages/bpg-cli",
]
EXPECTED_IMPORT_ROOTS = {
    "packages/bpg-core": "bpg_core",
    "packages/bpg-sdk": "bpg_sdk",
    "packages/bpg-temporal": "bpg_temporal",
    "packages/bpg-langgraph": "bpg_langgraph",
    "packages/bpg-cli": "bpg_cli",
}


def _load_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text())


def test_workspace_declares_expected_members() -> None:
    pyproject = _load_toml(REPO_ROOT / "pyproject.toml")
    assert pyproject["tool"]["uv"]["workspace"]["members"] == EXPECTED_WORKSPACE_MEMBERS


def test_workspace_packages_expose_expected_import_roots() -> None:
    for package_dir, import_root in EXPECTED_IMPORT_ROOTS.items():
        init_file = REPO_ROOT / package_dir / "src" / import_root / "__init__.py"
        assert init_file.exists(), f"missing import root for {package_dir}: {init_file}"


def test_package_ownership_rules_are_documented() -> None:
    doc = (REPO_ROOT / "docs" / "framework" / "package-ownership.md").read_text()
    for import_root in EXPECTED_IMPORT_ROOTS.values():
        assert f"`{import_root}`" in doc


def test_boundary_policy_covers_all_framework_packages() -> None:
    policy = _load_toml(REPO_ROOT / "packages" / "package-boundaries.toml")
    assert set(policy["packages"]) == set(EXPECTED_IMPORT_ROOTS.values())


def test_uv_workspace_sync_smoke(tmp_path: Path) -> None:
    if shutil.which("uv") is None:
        pytest.fail("uv is required to run this test but was not found on PATH")
    venv_dir = tmp_path / ".venv"
    import_roots = ", ".join(EXPECTED_IMPORT_ROOTS.values())
    smoke = (
        f"import {import_roots}; "
        "print('workspace-imports-ok')"
    )
    script = " && ".join(
        [
            f"uv venv {shlex.quote(str(venv_dir))}",
            f". {shlex.quote(str(venv_dir / 'bin' / 'activate'))}",
            "uv sync --active",
            f"python -c {shlex.quote(smoke)}",
            "bpg --help",
        ]
    )
    result = subprocess.run(
        ["bash", "-lc", f"set -euo pipefail; {script}"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    assert "workspace-imports-ok" in result.stdout
    assert "Business Process Graph" in result.stdout
