from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any

import yaml

from bpg.providers.base import Provider


DEFAULT_PROVIDER_REGISTRY_FILENAMES = ("bpg.providers.yaml", "bpg.providers.yml")


class ProviderRegistryError(Exception):
    """Raised when declarative provider registry loading fails."""


def find_default_provider_registry_file(cwd: Path | None = None) -> Path | None:
    root = cwd or Path.cwd()
    for filename in DEFAULT_PROVIDER_REGISTRY_FILENAMES:
        candidate = root / filename
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _resolve_entrypoint(value: Any, provider_id: str) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        entrypoint = value.get("class")
        if isinstance(entrypoint, str):
            return entrypoint
    raise ProviderRegistryError(
        f"providers.{provider_id} must be a 'module:Class' string or object with 'class'."
    )


def _load_provider_class(entrypoint: str, provider_id: str) -> type[Provider]:
    if ":" not in entrypoint:
        raise ProviderRegistryError(
            f"providers.{provider_id} must use 'module:Class' format; got {entrypoint!r}."
        )
    module_name, class_name = entrypoint.split(":", 1)
    try:
        module = importlib.import_module(module_name)
    except Exception as exc:
        raise ProviderRegistryError(
            f"Failed importing module {module_name!r} for provider {provider_id!r}: {exc}"
        ) from exc
    try:
        cls = getattr(module, class_name)
    except AttributeError as exc:
        raise ProviderRegistryError(
            f"Provider class {class_name!r} not found in module {module_name!r}."
        ) from exc
    if not isinstance(cls, type) or not issubclass(cls, Provider):
        raise ProviderRegistryError(
            f"{module_name}:{class_name} must be a subclass of bpg.providers.base.Provider."
        )
    class_provider_id = getattr(cls, "provider_id", None)
    if class_provider_id != provider_id:
        raise ProviderRegistryError(
            f"providers.{provider_id} points to class with provider_id={class_provider_id!r}; "
            "these must match."
        )
    return cls


def load_provider_registry_file(
    config_path: Path,
    *,
    registry: dict[str, type[Provider]],
) -> list[str]:
    if not config_path.exists():
        raise ProviderRegistryError(f"Provider registry file not found: {config_path}")
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        raise ProviderRegistryError(f"Failed reading provider registry file {config_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise ProviderRegistryError("Provider registry file root must be an object.")
    providers = raw.get("providers", {})
    if not isinstance(providers, dict):
        raise ProviderRegistryError("Provider registry 'providers' must be an object.")

    loaded_ids: list[str] = []
    for provider_id, config_value in providers.items():
        if not isinstance(provider_id, str) or not provider_id:
            raise ProviderRegistryError("Provider registry keys must be non-empty strings.")
        entrypoint = _resolve_entrypoint(config_value, provider_id)
        cls = _load_provider_class(entrypoint, provider_id)
        registry[provider_id] = cls
        loaded_ids.append(provider_id)
    return loaded_ids


def load_declared_providers(
    providers_file: Path | None,
    *,
    registry: dict[str, type[Provider]],
    cwd: Path | None = None,
) -> tuple[Path | None, list[str]]:
    config_path = providers_file or find_default_provider_registry_file(cwd=cwd)
    if config_path is None:
        return None, []
    loaded_ids = load_provider_registry_file(config_path, registry=registry)
    return config_path, loaded_ids
