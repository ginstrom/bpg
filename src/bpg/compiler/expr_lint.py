"""Expression linter for `when` conditions with token-level diagnostics."""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ExprToken:
    kind: str
    value: str
    start: int
    end: int


class ExprLintError(Exception):
    """Raised when a `when` expression fails linting/parsing."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        token: ExprToken | None = None,
        offset: int | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.token = token
        self.offset = offset

    @property
    def column(self) -> int | None:
        if self.token is not None:
            return self.token.start + 1
        if self.offset is not None:
            return self.offset + 1
        return None


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

_KNOWN_FUNCS: frozenset[str] = frozenset({"is_null", "is_present"})


def _tokenize(expr: str) -> list[ExprToken]:
    tokens: list[ExprToken] = []
    pos = 0
    while pos < len(expr):
        match = _TOKEN_SPEC.match(expr, pos)
        if not match:
            raise ExprLintError(
                "E_EXPR_TOKEN_UNEXPECTED_CHAR",
                f"unexpected character {expr[pos]!r}",
                offset=pos,
            )
        kind = match.lastgroup or ""
        value = match.group(0)
        start, end = match.span()
        pos = end
        if kind == "WS":
            continue
        tokens.append(ExprToken(kind=kind, value=value, start=start, end=end))
    return tokens


class _Parser:
    def __init__(self, tokens: list[ExprToken], expr_len: int) -> None:
        self._tokens = tokens
        self._pos = 0
        self._expr_len = expr_len

    def _peek(self) -> ExprToken | None:
        if self._pos < len(self._tokens):
            return self._tokens[self._pos]
        return None

    def _consume(self) -> ExprToken:
        tok = self._tokens[self._pos]
        self._pos += 1
        return tok

    def _expect(self, kind: str) -> ExprToken:
        tok = self._peek()
        if tok is None:
            raise ExprLintError(
                "E_EXPR_UNEXPECTED_END",
                f"expected {kind} but reached end of expression",
                offset=self._expr_len,
            )
        if tok.kind != kind:
            raise ExprLintError(
                "E_EXPR_EXPECTED_TOKEN",
                f"expected {kind} but got {tok.value!r}",
                token=tok,
            )
        return self._consume()

    def _at_end(self) -> bool:
        return self._pos >= len(self._tokens)

    def parse(self) -> None:
        self._or_expr()
        if not self._at_end():
            tok = self._peek()
            raise ExprLintError(
                "E_EXPR_UNEXPECTED_TOKEN",
                f"unexpected token {tok.value!r} after expression",
                token=tok,
            )

    def _or_expr(self) -> None:
        self._and_expr()
        while (tok := self._peek()) and tok.kind == "OP" and tok.value == "||":
            self._consume()
            self._and_expr()

    def _and_expr(self) -> None:
        self._not_expr()
        while (tok := self._peek()) and tok.kind == "OP" and tok.value == "&&":
            self._consume()
            self._not_expr()

    def _not_expr(self) -> None:
        tok = self._peek()
        if tok and tok.kind == "NOT":
            self._consume()
            self._not_expr()
            return
        self._cmp_expr()

    def _cmp_expr(self) -> None:
        self._primary()
        tok = self._peek()
        if tok and tok.kind == "OP" and tok.value in {"==", "!=", ">=", "<=", ">", "<"}:
            self._consume()
            self._primary()

    def _primary(self) -> None:
        tok = self._peek()
        if tok is None:
            raise ExprLintError(
                "E_EXPR_UNEXPECTED_END",
                "unexpected end of expression",
                offset=self._expr_len,
            )

        if tok.kind == "LPAREN":
            self._consume()
            self._or_expr()
            self._expect("RPAREN")
            return

        if tok.kind in {"STRING", "FLOAT", "INT"}:
            self._consume()
            return
        if tok.kind == "WORD" and tok.value in {"true", "false", "null"}:
            self._consume()
            return

        if tok.kind == "WORD":
            ident = self._consume()
            next_tok = self._peek()
            if next_tok and next_tok.kind == "LPAREN":
                if ident.value not in _KNOWN_FUNCS:
                    raise ExprLintError(
                        "E_EXPR_UNKNOWN_FUNCTION",
                        f"unknown function {ident.value!r}",
                        token=ident,
                    )
                self._consume()
                self._primary()
                self._expect("RPAREN")
            return

        raise ExprLintError(
            "E_EXPR_UNEXPECTED_TOKEN",
            f"unexpected token {tok.value!r}",
            token=tok,
        )


def lint_when_expression(expr: str) -> None:
    """Validate expression syntax and raise ExprLintError on failure."""
    tokens = _tokenize(expr)
    if not tokens:
        raise ExprLintError(
            "E_EXPR_EMPTY",
            "empty expression",
            offset=0,
        )
    _Parser(tokens, expr_len=len(expr)).parse()
