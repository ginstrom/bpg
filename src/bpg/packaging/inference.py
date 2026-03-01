from __future__ import annotations

import hashlib
import json
import os
import re
from typing import Any, Literal

from bpg.models.schema import Process
from bpg.providers import PROVIDER_REGISTRY
from bpg.packaging.runtime_spec import RuntimeSpec
from bpg.packaging.spec import EnvVarSpec


_ENV_PATTERN = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?:(:?[-?]).*?)?\}")


def _extract_env_refs(value: Any) -> list[tuple[str, bool]]:
    refs: list[tuple[str, bool]] = []
    if isinstance(value, str):
        for match in _ENV_PATTERN.finditer(value):
            name = match.group(1)
            op = match.group(2) or ""
            required = op == "" or op == ":?"
            refs.append((name, required))
    elif isinstance(value, dict):
        for nested in value.values():
            refs.extend(_extract_env_refs(nested))
    elif isinstance(value, list):
        for nested in value:
            refs.extend(_extract_env_refs(nested))
    return refs


def infer_ledger_backend(process: Process, mode: Literal["local", "package"] = "package") -> str:
    tags = process.policy.audit.tags if process.policy and process.policy.audit else None
    raw = tags.get("ledger_backend") if isinstance(tags, dict) else None
    if isinstance(raw, str):
        normalized = raw.strip().lower()
        if normalized in {"postgres", "sqlite-file", "sqlite-memory"}:
            return normalized
    return "sqlite-file" if mode == "local" else "postgres"


def build_runtime_spec(
    process: Process,
    process_file_text: str,
    mode: Literal["local", "package"],
    env: dict[str, str] | None = None,
    dashboard: bool = False,
    dashboard_port: int = 8080,
    image: str | None = None,
) -> RuntimeSpec:
    env_map = dict(os.environ)
    if env:
        env_map.update(env)

    services: set[str] = set()
    ledger_backend = infer_ledger_backend(process, mode=mode)

    defaults: dict[str, str] = {"BPG_LEDGER_BACKEND": ledger_backend}
    if ledger_backend == "postgres":
        defaults.update(
            {
                "POSTGRES_DB": "bpg",
                "POSTGRES_USER": "bpg",
                "POSTGRES_PASSWORD": "bpg",
                "BPG_LEDGER_DSN": "postgresql://bpg:bpg@postgres:5432/bpg",
            }
        )
    else:
        defaults["BPG_LEDGER_PATH"] = "./state/ledger.sqlite"
    for key, value in defaults.items():
        env_map.setdefault(key, value)

    if ledger_backend == "postgres":
        services.add("postgres")
    if dashboard:
        services.add("dashboard")

    env_entries: dict[str, EnvVarSpec] = {}

    def _add_env(name: str, required: bool, source: str) -> None:
        existing = env_entries.get(name)
        value = env_map.get(name)
        if existing is None:
            env_entries[name] = EnvVarSpec(
                name=name,
                required=required,
                value=value,
                source=source,
            )
            return
        env_entries[name] = EnvVarSpec(
            name=name,
            required=existing.required or required,
            value=existing.value if existing.value is not None else value,
            source=existing.source or source,
        )

    # Infer requirements from provider hooks and env placeholders in node config.
    for node_name, node in process.nodes.items():
        node_type = process.node_types[node.node_type]
        provider_cls = PROVIDER_REGISTRY.get(node_type.provider)
        if provider_cls:
            provider = provider_cls()
            requirements = provider.packaging_requirements(dict(node.config))
            for service in requirements.get("services", []):
                if isinstance(service, str) and service:
                    services.add(service)
            for var in requirements.get("required_env", []):
                if isinstance(var, str) and var:
                    _add_env(var, True, f"provider:{node_type.provider}")
            for var in requirements.get("optional_env", []):
                if isinstance(var, str) and var:
                    _add_env(var, False, f"provider:{node_type.provider}")
        for env_name, required in _extract_env_refs(dict(node.config)):
            _add_env(env_name, required, f"node:{node_name}")

    # Core runtime env tied to selected ledger backend.
    _add_env("BPG_LEDGER_BACKEND", True, "runtime")
    if ledger_backend == "postgres":
        _add_env("POSTGRES_DB", True, "postgres")
        _add_env("POSTGRES_USER", True, "postgres")
        _add_env("POSTGRES_PASSWORD", True, "postgres")
        _add_env("BPG_LEDGER_DSN", True, "runtime")
    else:
        _add_env("BPG_LEDGER_PATH", True, "runtime")
    if dashboard:
        env_map.setdefault("DASHBOARD_PORT", str(dashboard_port))
        _add_env("DASHBOARD_PORT", True, "dashboard")

    process_name = process.metadata.name if process.metadata else "default"
    process_hash = hashlib.sha256(process_file_text.encode("utf-8")).hexdigest()
    package_image_override = image or env_map.get("BPG_PACKAGE_IMAGE")
    if mode == "local":
        runtime_image = "bpg-local:dev"
        package_local_build = False
    elif package_image_override:
        runtime_image = package_image_override
        package_local_build = False
    else:
        runtime_image = "bpg-package:local"
        package_local_build = True

    return RuntimeSpec(
        process_name=process_name,
        process_hash=process_hash,
        mode=mode,
        ledger_backend=ledger_backend,
        runtime_image=runtime_image,
        package_local_build=package_local_build,
        dashboard_enabled=dashboard,
        dashboard_port=dashboard_port,
        services=sorted(services),
        env_vars=sorted(env_entries.values(), key=lambda item: item.name),
    )


def infer_package_spec(process: Process, process_file_text: str, env: dict[str, str] | None = None) -> RuntimeSpec:
    return build_runtime_spec(process, process_file_text, mode="package", env=env)


def build_package_metadata(spec: RuntimeSpec) -> dict[str, Any]:
    unresolved = spec.unresolved_required_env
    return {
        "process_name": spec.process_name,
        "process_hash": spec.process_hash,
        "mode": spec.mode,
        "ledger_backend": spec.ledger_backend,
        "dashboard_enabled": spec.dashboard_enabled,
        "dashboard_port": spec.dashboard_port,
        "runtime_image": spec.runtime_image,
        "services": list(spec.services),
        "ready_to_run": spec.ready_to_run,
        "unresolved_required_vars": unresolved,
    }


def metadata_json(spec: RuntimeSpec) -> str:
    return json.dumps(build_package_metadata(spec), indent=2, sort_keys=True) + "\n"
