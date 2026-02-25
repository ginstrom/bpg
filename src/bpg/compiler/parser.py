"""BPG process file parser.

Responsible for reading ``.bpg.yaml`` files from disk and deserializing them
into the BPG domain model.  The parser performs only syntactic validation
(well-formed YAML, required top-level keys present); semantic validation is
handled by the validator module.

Supported file conventions:
    process.bpg.yaml    — process definition
    types.bpg.yaml      — shared type registry
    node_types.bpg.yaml — shared node type registry
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from bpg.models.schema import Process


class ParseError(Exception):
    """Raised when a .bpg.yaml file cannot be parsed into a valid structure."""

    def __init__(self, message: str, file: Path | None = None) -> None:
        location = f" [{file}]" if file else ""
        super().__init__(f"ParseError{location}: {message}")
        self.file = file


def load_yaml_file(path: Path) -> Dict[str, Any]:
    """Read and parse a YAML file from disk.

    Args:
        path: Absolute or relative path to the YAML file.

    Returns:
        Parsed YAML content as a plain dict.

    Raises:
        ParseError: If the file cannot be read or is not valid YAML.
    """
    if not path.exists():
        raise ParseError("File not found", file=path)

    try:
        with path.open("r", encoding="utf-8") as f:
            content = yaml.safe_load(f)
            if content is None:
                return {}
            if not isinstance(content, dict):
                raise ParseError("YAML content must be a dictionary", file=path)
            return content
    except yaml.YAMLError as e:
        raise ParseError(f"Invalid YAML: {e}", file=path)
    except Exception as e:
        raise ParseError(f"Unexpected error reading file: {e}", file=path)


def parse_process_file(path: Path) -> Process:
    """Parse a ``process.bpg.yaml`` file into a ``Process`` domain model.

    Performs structural deserialization only.  Call ``validate_process`` on the
    result to enforce semantic rules (type resolution, cycle detection, etc.).

    Args:
        path: Path to the process definition YAML file.

    Returns:
        A fully-populated ``Process`` instance.

    Raises:
        ParseError: If the file is missing required sections or malformed.
    """
    raw = load_yaml_file(path)
    try:
        return Process.model_validate(raw)
    except Exception as e:
        # Pydantic errors can be verbose; for Phase 1 we just wrap them.
        raise ParseError(f"Process validation failed: {e}", file=path)
