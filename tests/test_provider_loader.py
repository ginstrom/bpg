from __future__ import annotations

from pathlib import Path
import sys
import types

import pytest

from bpg.providers.base import (
    ExecutionContext,
    ExecutionHandle,
    ExecutionStatus,
    Provider,
)
from bpg.providers.loader import (
    ProviderRegistryError,
    find_default_provider_registry_file,
    load_provider_registry_file,
)


class _ValidProvider(Provider):
    provider_id = "custom.echo"

    def invoke(self, input, config, context: ExecutionContext) -> ExecutionHandle:
        return ExecutionHandle(
            handle_id=context.idempotency_key,
            idempotency_key=context.idempotency_key,
            provider_id=self.provider_id,
            provider_data={"status": ExecutionStatus.COMPLETED, "output": dict(input)},
        )

    def poll(self, handle: ExecutionHandle) -> ExecutionStatus:
        return ExecutionStatus.COMPLETED

    def await_result(self, handle: ExecutionHandle, timeout=None):
        _ = timeout
        return dict(handle.provider_data.get("output", {}))

    def cancel(self, handle: ExecutionHandle) -> None:
        _ = handle


class _WrongIdProvider(_ValidProvider):
    provider_id = "mismatch.id"


def test_find_default_provider_registry_file(tmp_path: Path) -> None:
    default_path = tmp_path / "bpg.providers.yaml"
    default_path.write_text("providers: {}\n", encoding="utf-8")
    assert find_default_provider_registry_file(tmp_path) == default_path


def test_load_provider_registry_file_registers_provider(tmp_path: Path) -> None:
    module_name = "tests_fake_provider_loader_ok"
    module = types.ModuleType(module_name)
    module.ValidProvider = _ValidProvider
    sys.modules[module_name] = module

    config = tmp_path / "bpg.providers.yaml"
    config.write_text(
        f"providers:\n  custom.echo: {module_name}:ValidProvider\n",
        encoding="utf-8",
    )
    registry: dict[str, type[Provider]] = {}
    loaded = load_provider_registry_file(config, registry=registry)
    assert loaded == ["custom.echo"]
    assert registry["custom.echo"] is _ValidProvider


def test_load_provider_registry_file_rejects_provider_id_mismatch(tmp_path: Path) -> None:
    module_name = "tests_fake_provider_loader_bad"
    module = types.ModuleType(module_name)
    module.BadProvider = _WrongIdProvider
    sys.modules[module_name] = module

    config = tmp_path / "bpg.providers.yaml"
    config.write_text(
        f"providers:\n  custom.echo: {module_name}:BadProvider\n",
        encoding="utf-8",
    )
    with pytest.raises(ProviderRegistryError, match="provider_id"):
        load_provider_registry_file(config, registry={})
