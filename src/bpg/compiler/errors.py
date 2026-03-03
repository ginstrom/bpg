"""Structured compiler diagnostics for machine-readable error handling."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class CompilerDiagnostic:
    """Canonical diagnostic payload emitted by parser/validator errors."""

    error_code: str
    path: str
    message: str
    fix: str | None = None
    example_patch: list[dict[str, Any]] = field(default_factory=list)
    schema_excerpt: dict[str, Any] = field(default_factory=dict)
    severity: str = "error"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

