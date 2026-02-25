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
    # TODO: implement
    raise NotImplementedError(f"load_yaml_file not yet implemented (path={path})")


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
    # TODO: implement
    #   1. load_yaml_file(path)
    #   2. Extract and build TypeDef map from raw["types"]
    #   3. Extract and build NodeType map from raw["node_types"]
    #   4. Build NodeInstance list from raw["nodes"]
    #   5. Build Edge list from raw["edges"]
    #   6. Construct and return Process(...)
    raise NotImplementedError(f"parse_process_file not yet implemented (path={path})")
