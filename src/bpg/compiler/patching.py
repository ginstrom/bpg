"""JSON patch helpers for process spec editing."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any


class PatchApplyError(Exception):
    """Raised when a patch operation cannot be applied."""


def load_patch_file(path: Path) -> list[dict[str, Any]]:
    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise PatchApplyError(f"Invalid patch JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise PatchApplyError("Patch file must contain a JSON array of operations.")
    return payload


def _parse_path(path: str) -> list[str | int]:
    if path == "$":
        return []
    if not path.startswith("$."):
        raise PatchApplyError(f"Unsupported patch path: {path}")
    remainder = path[2:]
    tokens: list[str | int] = []
    for part in remainder.split("."):
        if not part:
            continue
        cursor = 0
        while cursor < len(part):
            match = re.match(r"([^\[\]]+)|\[(\d+)\]", part[cursor:])
            if not match:
                raise PatchApplyError(f"Invalid path segment: {part}")
            key, index = match.groups()
            if key is not None:
                tokens.append(key)
            else:
                tokens.append(int(index))
            cursor += len(match.group(0))
    return tokens


def _resolve_parent(doc: Any, tokens: list[str | int]) -> tuple[Any, str | int]:
    if not tokens:
        raise PatchApplyError("Patch path cannot target document root directly.")
    parent_tokens = tokens[:-1]
    target = tokens[-1]
    current = doc
    for tok in parent_tokens:
        if isinstance(tok, int):
            if not isinstance(current, list) or tok >= len(current):
                raise PatchApplyError("Path index out of range.")
            current = current[tok]
        else:
            if not isinstance(current, dict) or tok not in current:
                raise PatchApplyError(f"Path key not found: {tok}")
            current = current[tok]
    return current, target


def apply_json_patch(document: dict[str, Any], operations: list[dict[str, Any]]) -> dict[str, Any]:
    doc = copy.deepcopy(document)
    for op in operations:
        if not isinstance(op, dict):
            raise PatchApplyError("Patch operation must be an object.")
        action = op.get("op")
        path = op.get("path")
        if not isinstance(action, str) or not isinstance(path, str):
            raise PatchApplyError("Patch operation requires string 'op' and 'path'.")

        tokens = _parse_path(path)
        if not tokens:
            raise PatchApplyError("Root-level patch operations are not supported.")
        parent, target = _resolve_parent(doc, tokens)

        if action in {"add", "replace"}:
            if "value" not in op:
                raise PatchApplyError(f"Patch op '{action}' requires 'value'.")
            value = op["value"]
            if isinstance(target, int):
                if not isinstance(parent, list):
                    raise PatchApplyError("List index target requires list parent.")
                if action == "add":
                    if target > len(parent):
                        raise PatchApplyError("List add index out of range.")
                    parent.insert(target, value)
                else:
                    if target >= len(parent):
                        raise PatchApplyError("List replace index out of range.")
                    parent[target] = value
            else:
                if not isinstance(parent, dict):
                    raise PatchApplyError("Object key target requires dict parent.")
                parent[target] = value
        elif action == "remove":
            if isinstance(target, int):
                if not isinstance(parent, list) or target >= len(parent):
                    raise PatchApplyError("List remove index out of range.")
                del parent[target]
            else:
                if not isinstance(parent, dict) or target not in parent:
                    raise PatchApplyError(f"Path key not found for remove: {target}")
                del parent[target]
        else:
            raise PatchApplyError(f"Unsupported patch op: {action}")
    return doc
