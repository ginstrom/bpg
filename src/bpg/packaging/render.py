from __future__ import annotations

from datetime import datetime, timezone
import json

import yaml

from bpg.packaging.inference import build_package_metadata
from bpg.packaging.runtime_spec import RuntimeSpec
from bpg.packaging.spec import EnvVarSpec


def render_env(env_vars: list[EnvVarSpec], include_comments: bool = False) -> str:
    lines: list[str] = []
    for item in sorted(env_vars, key=lambda x: x.name):
        if include_comments and item.description:
            lines.append(f"# {item.description}")
        if item.required:
            value = item.value if item.value not in (None, "") else "__REQUIRED__"
            lines.append(f"{item.name}={value}")
        elif item.value not in (None, ""):
            lines.append(f"{item.name}={item.value}")
        else:
            lines.append(f"# {item.name}=")
    return "\n".join(lines) + "\n"


def render_env_example(env_vars: list[EnvVarSpec]) -> str:
    lines: list[str] = []
    for item in sorted(env_vars, key=lambda x: x.name):
        marker = "__REQUIRED__" if item.required else ""
        lines.append(f"{item.name}={marker}")
    return "\n".join(lines) + "\n"


def render_compose(spec: RuntimeSpec) -> str:
    runtime_container: dict[str, object] = {"image": spec.runtime_image}
    if spec.mode == "package" and spec.package_local_build:
        runtime_container["build"] = {
            "context": ".",
            "dockerfile": "Dockerfile",
        }
        runtime_container["pull_policy"] = "never"

    bpg_service: dict = {
        **runtime_container,
        "env_file": [".env"],
        "volumes": ["./process.bpg.yaml:/app/process.bpg.yaml:ro", "./state:/app/.bpg-state"],
        "command": ["run", spec.process_name],
    }
    # Dashboard mode is trigger-driven; keep worker container optional.
    if spec.dashboard_enabled:
        bpg_service["profiles"] = ["runner"]
    services: dict = {"bpg": bpg_service}
    if "postgres" in spec.services:
        services["postgres"] = {
            "image": "postgres:16",
            "environment": {
                "POSTGRES_DB": "${POSTGRES_DB}",
                "POSTGRES_USER": "${POSTGRES_USER}",
                "POSTGRES_PASSWORD": "${POSTGRES_PASSWORD}",
            },
            "ports": ["5432:5432"],
            "volumes": ["postgres-data:/var/lib/postgresql/data"],
        }
    if "redis" in spec.services:
        services["redis"] = {
            "image": "redis:7",
            "ports": ["6379:6379"],
        }
    if spec.dashboard_enabled:
        services["dashboard"] = {
            **runtime_container,
            "env_file": [".env"],
            "environment": {
                "BPG_STATE_DIR": "/app/.bpg-state",
                "BPG_PROCESS_NAME": spec.process_name,
                "BPG_PROCESS_FILE": "/app/process.bpg.yaml",
                "DASHBOARD_PORT": "${DASHBOARD_PORT}",
            },
            "volumes": ["./process.bpg.yaml:/app/process.bpg.yaml:ro", "./state:/app/.bpg-state"],
            "ports": [f"{spec.dashboard_port}:{spec.dashboard_port}"],
            "entrypoint": ["python", "-m", "bpg.dashboard.server"],
        }

    compose = {"name": f"bpg-{spec.process_name}", "services": services}
    if "postgres" in spec.services:
        compose["volumes"] = {"postgres-data": {}}
    return yaml.safe_dump(compose, sort_keys=False)


def render_readme(spec: RuntimeSpec) -> str:
    unresolved = spec.unresolved_required_env
    checklist = "\n".join(f"- Set `{name}` in `.env`" for name in unresolved) or "- None"
    services = ", ".join(spec.services) if spec.services else "none"
    return (
        "# BPG Package\n\n"
        f"Process: `{spec.process_name}`\n\n"
        f"Inferred services: {services}\n\n"
        "## Run\n\n"
        "```bash\n"
        "docker compose up --build\n"
        "```\n\n"
        "## Before First Run\n\n"
        f"{checklist}\n"
    )


def render_metadata(spec: RuntimeSpec) -> str:
    metadata = build_package_metadata(spec)
    metadata["generated_at"] = datetime.now(timezone.utc).isoformat()
    return json.dumps(metadata, indent=2, sort_keys=True) + "\n"
