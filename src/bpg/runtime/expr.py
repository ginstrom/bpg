"""BPG expression evaluator for ``when`` conditions and ``with`` mapping resolution.

Public API
----------
eval_when(expr, state, trigger_name) -> bool
    Evaluate a compiled BPG ``when`` expression against a RunState snapshot.

resolve_mapping(mapping, state, trigger_name) -> Dict[str, Any]
    Resolve a ``with`` mapping block to concrete Python values.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from bpg.runtime.state import RunState


# ---------------------------------------------------------------------------
# Tokenizer (same spec as compiler/ir.py _TOKEN_SPEC)
# ---------------------------------------------------------------------------

_TOKEN_SPEC = re.compile(
    r"""
    (?P<WS>     \s+)                           |
    (?P<STRING> "[^"]*" | '[^']*')             |
    (?P<FLOAT>  \d+\.\d+)                      |
    (?P<INT>    \d+)                            |
    (?P<OP>     ==|!=|>=|<=|\|\||&&|[><])      |
    (?P<NOT>    !)                              |
    (?P<LPAREN> \()                             |
    (?P<RPAREN> \))                             |
    (?P<COMMA>  ,)                              |
    (?P<WORD>   [a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)*)
    """,
    re.VERBOSE,
)


class _EvalError(Exception):
    """Raised when expression evaluation fails at runtime."""


def _tokenize(expr: str) -> List[Tuple[str, str]]:
    tokens: List[Tuple[str, str]] = []
    pos = 0
    for m in _TOKEN_SPEC.finditer(expr):
        if m.start() != pos:
            raise _EvalError(f"unexpected character(s) {expr[pos:m.start()]!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "WS":
            continue
        tokens.append((kind, m.group()))
    if pos != len(expr):
        raise _EvalError(f"unexpected character(s) {expr[pos:]!r}")
    return tokens


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------

def _resolve_path(path: str, state: RunState, trigger_name: str) -> Any:
    """Resolve a dotted BPG path (e.g. ``triage.out.risk``) to a Python value.

    Supported path forms:
    - ``<node>.out.<field>`` — look up field in ``state["node_outputs"][node]``
    - ``<node>.in.<field>``  — not produced at runtime; raise informative error
    - ``trigger.in.<field>`` — look up field in ``state["trigger_input"]``

    Args:
        path: Dotted reference string.
        state: Current RunState snapshot.
        trigger_name: Actual name of the trigger node (resolves alias ``"trigger"``).

    Returns:
        The resolved Python value.

    Raises:
        _EvalError: If the path cannot be resolved.
    """
    parts = path.split(".")
    if len(parts) < 3:
        raise _EvalError(
            f"path {path!r} must have at least 3 segments (node.segment.field)"
        )

    node_ref = parts[0]
    segment = parts[1]
    field_parts = parts[2:]

    # Resolve "trigger" alias to actual trigger node name
    if node_ref == "trigger":
        if segment == "in":
            # trigger.in.field → look up in trigger_input
            data = state["trigger_input"]
            value: Any = data
            for part in field_parts:
                if not isinstance(value, dict):
                    raise _EvalError(
                        f"cannot index into non-dict at {path!r} (got {type(value).__name__})"
                    )
                value = value.get(part)
            return value
        # trigger.out.* → treat as regular node output for trigger_name
        node_ref = trigger_name

    if segment == "out":
        outputs = state["node_outputs"]
        if node_ref not in outputs:
            raise _EvalError(f"no outputs recorded for node {node_ref!r}")
        data = outputs[node_ref]
        value = data
        for part in field_parts:
            if not isinstance(value, dict):
                raise _EvalError(
                    f"cannot index into non-dict at {path!r} (got {type(value).__name__})"
                )
            value = value.get(part)
        return value

    raise _EvalError(f"unsupported path segment {segment!r} in {path!r}")


# ---------------------------------------------------------------------------
# Recursive-descent evaluator
# ---------------------------------------------------------------------------
#
# Grammar (mirrors compiler/ir.py _Parser, adding value semantics):
#
#   expr     = or_expr
#   or_expr  = and_expr ('||' and_expr)*
#   and_expr = not_expr ('&&' not_expr)*
#   not_expr = '!' not_expr | cmp_expr
#   cmp_expr = primary (('=='|'!='|'>='|'<='|'>'|'<') primary)?
#   primary  = func_call | '(' expr ')' | literal | path
#   func_call = ('is_null'|'is_present') '(' primary ')'
#   literal  = STRING | FLOAT | INT | 'true' | 'false' | 'null'
#   path     = WORD   (dotted paths are a single WORD token)


class _Evaluator:
    """Evaluate a tokenized BPG ``when`` expression against a RunState."""

    def __init__(
        self,
        tokens: List[Tuple[str, str]],
        state: RunState,
        trigger_name: str,
    ) -> None:
        self._tokens = tokens
        self._pos = 0
        self._state = state
        self._trigger_name = trigger_name

    # -- Helpers -----------------------------------------------------------

    def _peek(self) -> Optional[Tuple[str, str]]:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _consume(self) -> Tuple[str, str]:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, kind: str) -> Tuple[str, str]:
        tok = self._peek()
        if tok is None or tok[0] != kind:
            got = repr(tok[1]) if tok else "end of expression"
            raise _EvalError(f"expected {kind}, got {got}")
        return self._consume()

    def _at_end(self) -> bool:
        return self._pos >= len(self._tokens)

    # -- Grammar rules -----------------------------------------------------

    def evaluate(self) -> Any:
        result = self._or_expr()
        if not self._at_end():
            tok = self._peek()
            raise _EvalError(f"unexpected token {tok[1]!r} after expression")
        return result

    def _or_expr(self) -> Any:
        left = self._and_expr()
        while self._peek() == ("OP", "||"):
            self._consume()
            right = self._and_expr()
            left = bool(left) or bool(right)
        return left

    def _and_expr(self) -> Any:
        left = self._not_expr()
        while self._peek() == ("OP", "&&"):
            self._consume()
            right = self._not_expr()
            left = bool(left) and bool(right)
        return left

    def _not_expr(self) -> Any:
        if self._peek() and self._peek()[0] == "NOT":
            self._consume()
            return not bool(self._not_expr())
        return self._cmp_expr()

    def _cmp_expr(self) -> Any:
        left = self._primary()
        tok = self._peek()
        if tok and tok[0] == "OP" and tok[1] in {"==", "!=", ">=", "<=", ">", "<"}:
            op = self._consume()[1]
            right = self._primary()
            return _apply_cmp(op, left, right)
        return left

    def _primary(self) -> Any:
        tok = self._peek()
        if tok is None:
            raise _EvalError("unexpected end of expression")

        kind, value = tok

        # Grouped expression
        if kind == "LPAREN":
            self._consume()
            result = self._or_expr()
            self._expect("RPAREN")
            return result

        # Literals
        if kind == "STRING":
            self._consume()
            # Strip surrounding quotes
            return value[1:-1]
        if kind == "FLOAT":
            self._consume()
            return float(value)
        if kind == "INT":
            self._consume()
            return int(value)
        if kind == "WORD" and value == "true":
            self._consume()
            return True
        if kind == "WORD" and value == "false":
            self._consume()
            return False
        if kind == "WORD" and value == "null":
            self._consume()
            return None

        # WORD — function call or path reference
        if kind == "WORD":
            self._consume()
            next_tok = self._peek()
            if next_tok and next_tok[0] == "LPAREN":
                # Function call: is_null or is_present
                self._consume()  # consume LPAREN
                arg = self._primary()
                self._expect("RPAREN")
                if value == "is_null":
                    return arg is None
                if value == "is_present":
                    return arg is not None
                raise _EvalError(f"unknown function {value!r}")
            # Path reference
            return _resolve_path(value, self._state, self._trigger_name)

        raise _EvalError(f"unexpected token {value!r}")


def _apply_cmp(op: str, left: Any, right: Any) -> bool:
    """Apply a comparison operator to two Python values."""
    try:
        if op == "==":
            return left == right
        if op == "!=":
            return left != right
        if op == ">":
            return left > right  # type: ignore[operator]
        if op == "<":
            return left < right  # type: ignore[operator]
        if op == ">=":
            return left >= right  # type: ignore[operator]
        if op == "<=":
            return left <= right  # type: ignore[operator]
    except TypeError as exc:
        raise _EvalError(
            f"cannot compare {left!r} {op} {right!r}: {exc}"
        ) from exc
    raise _EvalError(f"unknown operator {op!r}")  # pragma: no cover


# ---------------------------------------------------------------------------
# Public: eval_when
# ---------------------------------------------------------------------------


def eval_when(expr: str, state: RunState, trigger_name: str) -> bool:
    """Evaluate a BPG ``when`` expression against the current run state.

    Expressions were already syntax-validated by the compiler; this function
    evaluates them to a boolean at runtime.

    Args:
        expr: Raw ``when`` expression string, e.g. ``triage.out.risk == "high"``.
        state: Current :class:`RunState` snapshot.
        trigger_name: The actual name of the trigger node in the process.

    Returns:
        ``True`` if the edge should fire, ``False`` otherwise.

    Raises:
        _EvalError: If the expression cannot be evaluated (missing data, etc.).
    """
    tokens = _tokenize(expr)
    evaluator = _Evaluator(tokens, state, trigger_name)
    result = evaluator.evaluate()
    return bool(result)


# ---------------------------------------------------------------------------
# Public: resolve_mapping
# ---------------------------------------------------------------------------

# Pattern matching a plain dotted field reference: word.word.word (no {{ }})
_RE_FIELD_REF = re.compile(r"^[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+$")

# Pattern matching interpolated segments: {{expr}} inside a string
_RE_INTERPOLATE = re.compile(r"\{\{([^}]+)\}\}")


def _coerce_literal(value: str) -> Any:
    """Coerce a plain string literal to a Python native type where obvious.

    Conversions applied (in order):
    - ``"true"`` / ``"false"``  → bool
    - Numeric string (int or float) → int / float
    - Anything else → str
    """
    if value == "true":
        return True
    if value == "false":
        return False
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value


def resolve_mapping(
    mapping: Dict[str, str],
    state: RunState,
    trigger_name: str,
) -> Dict[str, Any]:
    """Resolve a BPG ``with`` mapping block to concrete Python values.

    For each value in the mapping:
    - If it contains ``{{expr}}`` interpolation markers → evaluate each
      embedded expression and substitute into the surrounding string.
    - Elif it looks like a dotted field reference (``node.out.field``) →
      resolve the path against the state.
    - Else → treat as a plain literal, applying lightweight type coercion.

    Args:
        mapping: The raw ``with`` mapping dict from an edge definition.
        state: Current :class:`RunState` snapshot.
        trigger_name: Actual trigger node name.

    Returns:
        Dict with the same keys, but values resolved to Python objects.
    """
    result: Dict[str, Any] = {}
    for key, raw_value in mapping.items():
        result[key] = _resolve_value(raw_value, state, trigger_name)
    return result


def _resolve_value(raw: str, state: RunState, trigger_name: str) -> Any:
    """Resolve a single mapping value to a Python object."""
    # String interpolation: contains {{ }}
    if "{{" in raw:
        def _substitute(m: re.Match) -> str:
            inner_expr = m.group(1).strip()
            resolved = _resolve_path(inner_expr, state, trigger_name)
            return str(resolved) if resolved is not None else ""

        return _RE_INTERPOLATE.sub(_substitute, raw)

    # Plain dotted field reference
    if _RE_FIELD_REF.match(raw):
        return _resolve_path(raw, state, trigger_name)

    # Literal value — coerce if unambiguous
    return _coerce_literal(raw)
