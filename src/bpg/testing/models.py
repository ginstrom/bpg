"""Models for spec-level BPG tests (`bpg test`)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SpecTestExpectation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path_contains: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(default_factory=list)
    event_sequence: list[str] = Field(default_factory=list)


class SpecTestCase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    input: dict[str, Any] = Field(default_factory=dict)
    mocks: dict[str, dict[str, Any]] = Field(default_factory=dict)
    expect: SpecTestExpectation = Field(default_factory=SpecTestExpectation)


class SpecTestSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    process_file: str | None = None
    tests: list[SpecTestCase]

    def resolve_process_file(self, suite_path: Path) -> Path:
        if self.process_file:
            return (suite_path.parent / self.process_file).resolve()
        return (suite_path.parent / "process.bpg.yaml").resolve()
