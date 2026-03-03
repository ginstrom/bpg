"""Canonical formatting for process YAML specs."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from bpg.compiler.normalize import normalize_process_dict
from bpg.compiler.parser import ParseError


def format_process_text(text: str) -> str:
    raw: Any = yaml.safe_load(text)
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise ParseError("YAML content must be a dictionary")
    normalized = normalize_process_dict(raw)
    return yaml.safe_dump(normalized, sort_keys=False).rstrip() + "\n"


def format_process_file(path: Path) -> tuple[str, bool]:
    original = path.read_text()
    formatted = format_process_text(original)
    return formatted, formatted != original
