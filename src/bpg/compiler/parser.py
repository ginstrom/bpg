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
    raw = _load_with_imports(path.resolve(), stack=[])
    try:
        return Process.model_validate(raw)
    except Exception as e:
        # Pydantic errors can be verbose; for Phase 1 we just wrap them.
        raise ParseError(f"Process validation failed: {e}", file=path)


def _load_with_imports(path: Path, stack: list[Path]) -> Dict[str, Any]:
    """Load YAML and recursively merge imported registries."""
    if path in stack:
        cycle = " -> ".join(str(p) for p in stack + [path])
        raise ParseError(f"Import cycle detected: {cycle}", file=path)
    raw = load_yaml_file(path)
    imports = raw.get("imports", []) or []
    if not isinstance(imports, list):
        raise ParseError("'imports' must be a list of file paths", file=path)

    merged: Dict[str, Dict[str, Any]] = {"types": {}, "node_types": {}, "modules": {}}
    for import_item in imports:
        if not isinstance(import_item, str):
            raise ParseError("imports entries must be strings", file=path)
        import_path = (path.parent / import_item).resolve()
        imported_raw = _load_with_imports(import_path, stack=stack + [path])
        for section in ("types", "node_types", "modules"):
            imported_section = imported_raw.get(section, {}) or {}
            if not isinstance(imported_section, dict):
                raise ParseError(f"Imported section '{section}' must be a mapping", file=import_path)
            for key, val in imported_section.items():
                existing = merged[section].get(key)
                if existing is not None and existing != val:
                    raise ParseError(
                        f"Conflicting imported definition for {section}.{key!r}",
                        file=path,
                    )
                merged[section][key] = val

    for section in ("types", "node_types", "modules"):
        local_section = raw.get(section, {}) or {}
        if not isinstance(local_section, dict):
            raise ParseError(f"Section '{section}' must be a mapping", file=path)
        if merged[section] or local_section:
            raw[section] = {**merged[section], **local_section}
    return raw
