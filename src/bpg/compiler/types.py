from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Tuple

# ---------------------------------------------------------------------------
# Primitive built-in type names
# ---------------------------------------------------------------------------

_PRIMITIVES: frozenset[str] = frozenset(
    {"string", "number", "bool", "duration", "datetime", "object"}
)


@dataclass(frozen=True)
class FieldType:
    """Parsed representation of a BPG type string.

    Examples::

        parse_field_type("string")         -> FieldType(base="string", optional=False)
        parse_field_type("number?")        -> FieldType(base="number", optional=True)
        parse_field_type("enum(S1,S2,S3)") -> FieldType(base="enum", optional=False,
                                                         enum_values=("S1","S2","S3"))
        parse_field_type("list<string>")   -> FieldType(base="list", optional=False,
                                                         list_element="string")
        parse_field_type("list<string>?")  -> FieldType(base="list", optional=True,
                                                         list_element="string")
    """

    base: str
    optional: bool
    enum_values: Tuple[str, ...] = ()
    list_element: str = ""

    @property
    def is_required(self) -> bool:
        """Return True when the field must be present in any mapping."""
        return not self.optional


def parse_field_type(type_str: str) -> FieldType:
    """Parse a BPG type string into a structured :class:`FieldType`.

    Supported forms:

    - ``string``          — primitive, required
    - ``string?``         — primitive, optional
    - ``enum(A,B,C)``     — enum, required
    - ``enum(A,B,C)?``    — enum, optional
    - ``list<string>``    — list, required
    - ``list<string>?``   — list, optional

    Args:
        type_str: A raw BPG field type string from a TypeDef.

    Returns:
        A frozen :class:`FieldType` instance.

    Raises:
        ValueError: If the type string cannot be parsed.
    """
    type_str = type_str.strip()

    optional = type_str.endswith("?")
    core = type_str[:-1].strip() if optional else type_str

    # enum(...)
    m = re.match(r"^enum\(([^)]+)\)$", core)
    if m:
        values_raw = m.group(1)
        values = tuple(v.strip() for v in values_raw.split(","))
        return FieldType(base="enum", optional=optional, enum_values=values)

    # list<...> with nested generic support.
    if core.startswith("list<") and core.endswith(">"):
        depth = 0
        for ch in core:
            if ch == "<":
                depth += 1
            elif ch == ">":
                depth -= 1
                if depth < 0:
                    raise ValueError(f"invalid list type: {type_str!r}")
        if depth != 0:
            raise ValueError(f"invalid list type: {type_str!r}")
        inner = core[5:-1].strip()
        if not inner:
            raise ValueError(f"invalid list type: {type_str!r}")
        # Validate nested list syntax early so malformed generics fail fast.
        if inner.startswith("list<"):
            parse_field_type(inner)
        return FieldType(base="list", optional=optional, list_element=inner)

    # primitive (may end with ?)
    base = core
    return FieldType(base=base, optional=optional)
