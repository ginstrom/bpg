from __future__ import annotations

import ast
import tomllib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "packages" / "package-boundaries.toml"


def _load_policy() -> dict:
    return tomllib.loads(POLICY_PATH.read_text())


def _iter_python_files(package_dir: Path):
    return sorted(
        path
        for path in package_dir.rglob("*.py")
        if "__pycache__" not in path.parts
    )


def _top_level_imports(module_path: Path) -> set[str]:
    tree = ast.parse(module_path.read_text(), filename=str(module_path))
    imports: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".", 1)[0])
    return imports


def test_framework_packages_only_use_declared_cross_package_imports() -> None:
    policy = _load_policy()["packages"]
    workspace_roots = set(policy)

    for package_name, package_policy in policy.items():
        package_dir = REPO_ROOT / package_policy["path"] / "src" / package_name
        allowed_workspace = set(package_policy.get("allowed_workspace_imports", []))
        allowed_legacy = set(package_policy.get("allowed_legacy_imports", []))

        for module_path in _iter_python_files(package_dir):
            imports = _top_level_imports(module_path)
            imported_workspace = (imports & workspace_roots) - {package_name}
            imported_legacy = imports & {"bpg"}

            assert imported_workspace <= allowed_workspace, (
                f"{module_path} imports undeclared workspace packages: "
                f"{sorted(imported_workspace - allowed_workspace)}"
            )
            assert imported_legacy <= allowed_legacy, (
                f"{module_path} imports undeclared legacy modules: "
                f"{sorted(imported_legacy - allowed_legacy)}"
            )
