from __future__ import annotations

import subprocess
from pathlib import Path

from bpg.packaging import render_compose, render_env, render_env_example, render_metadata, render_readme, write_package
from bpg.packaging.runtime_spec import RuntimeSpec


def _package_runtime_source_files() -> dict[str, str]:
    project_root = Path(__file__).resolve().parents[3]
    files: dict[str, str] = {}
    for relative_path in ("Dockerfile", "pyproject.toml", "uv.lock"):
        source_path = project_root / relative_path
        if source_path.exists():
            files[relative_path] = source_path.read_text()

    src_root = project_root / "src"
    if src_root.exists():
        for source_path in src_root.rglob("*.py"):
            if source_path.is_file():
                rel = source_path.relative_to(project_root).as_posix()
                files[rel] = source_path.read_text()
    return files


def build_runtime_bundle_files(process_text: str, spec: RuntimeSpec) -> dict[str, str]:
    files = {
        "docker-compose.yml": render_compose(spec),
        ".env.example": render_env_example(spec.env_vars),
        ".env": render_env(spec.env_vars),
        "process.bpg.yaml": process_text,
        "README.md": render_readme(spec),
        "package-metadata.json": render_metadata(spec),
        # Ensure bind-mount source exists for "./state:/app/.bpg-state".
        "state/.gitkeep": "",
    }
    if spec.mode == "package" and spec.package_local_build:
        files.update(_package_runtime_source_files())
    return files


def write_runtime_bundle(output_dir: Path, process_text: str, spec: RuntimeSpec, force: bool) -> None:
    files = build_runtime_bundle_files(process_text, spec)
    write_package(output_dir, files, force=force)


def compose_command(local_dir: Path, args: list[str]) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "compose"] + args
    return subprocess.run(cmd, cwd=local_dir, text=True, capture_output=True, check=False)


def build_image_command(image: str, context_dir: Path) -> subprocess.CompletedProcess[str]:
    cmd = ["docker", "build", "-t", image, "."]
    return subprocess.run(cmd, cwd=context_dir, text=True, capture_output=True, check=False)
