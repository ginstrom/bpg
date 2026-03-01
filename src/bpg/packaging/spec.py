from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class EnvVarSpec:
    name: str
    required: bool
    value: Optional[str] = None
    description: Optional[str] = None
    source: Optional[str] = None


@dataclass(frozen=True)
class PackageSpec:
    process_name: str
    process_hash: str
    services: list[str] = field(default_factory=list)
    env_vars: list[EnvVarSpec] = field(default_factory=list)


@dataclass
class PackageResult:
    output_dir: str
    unresolved_required_vars: list[str] = field(default_factory=list)

    @property
    def ready_to_run(self) -> bool:
        return not self.unresolved_required_vars
