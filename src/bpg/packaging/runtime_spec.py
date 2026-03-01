from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from bpg.packaging.spec import EnvVarSpec


@dataclass(frozen=True)
class RuntimeSpec:
    process_name: str
    process_hash: str
    mode: Literal["local", "package"]
    ledger_backend: str
    runtime_image: str
    package_local_build: bool = False
    dashboard_enabled: bool = False
    dashboard_port: int = 8080
    services: list[str] = field(default_factory=list)
    env_vars: list[EnvVarSpec] = field(default_factory=list)

    @property
    def required_env(self) -> list[str]:
        return [item.name for item in self.env_vars if item.required]

    @property
    def unresolved_required_env(self) -> list[str]:
        return [item.name for item in self.env_vars if item.required and not item.value]

    @property
    def ready_to_run(self) -> bool:
        return len(self.unresolved_required_env) == 0
