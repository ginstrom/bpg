"""BPG Execution Intermediate Representation (IR).

Performs the compile phase after structural validation:
  1. Resolves all type references into rich FieldType / ResolvedTypeDef structures.
  2. Type-checks every edge ``with`` mapping against the target node's ``in`` schema.
  3. Validates ``when`` expressions using a recursive-descent parser.
  4. Produces a topological sort (Kahn's algorithm) for execution ordering.
  5. Returns an ExecutionIR — a fully annotated, resolved process graph.

Public API
----------
parse_field_type(type_str)     Parse a BPG type string into a FieldType.
resolve_typedef(name, typedef) Convert a TypeDef into a ResolvedTypeDef.
compile_process(process)       Main entry point; requires validate_process() first.
"""

from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from bpg.compiler.validator import ValidationError
from bpg.models.schema import Edge, NodeInstance, NodeType, Process, TypeDef


# ---------------------------------------------------------------------------
# Primitive built-in type names (mirrors validator.py)
# ---------------------------------------------------------------------------

_PRIMITIVES: frozenset[str] = frozenset(
    {"string", "number", "bool", "duration", "datetime", "object"}
)


# ---------------------------------------------------------------------------
# IR data types
# ---------------------------------------------------------------------------


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


@dataclass
class ResolvedTypeDef:
    """TypeDef with each field string parsed into a FieldType.

    For primitive types (``object``, ``string``, etc.) used as node in/out
    types, ``fields`` will be an empty dict.
    """

    name: str
    fields: Dict[str, FieldType]

    def required_fields(self) -> List[str]:
        """Return names of fields whose FieldType.is_required is True."""
        return [name for name, ft in self.fields.items() if ft.is_required]

    def optional_fields(self) -> List[str]:
        """Return names of fields whose FieldType.is_required is False."""
        return [name for name, ft in self.fields.items() if not ft.is_required]


@dataclass
class ResolvedNode:
    """Node instance with type information fully resolved."""

    name: str
    instance: NodeInstance
    node_type: NodeType
    in_type: ResolvedTypeDef
    out_type: ResolvedTypeDef


@dataclass
class ResolvedEdge:
    """Edge with references to fully resolved source/target nodes."""

    edge: Edge
    source: ResolvedNode
    target: ResolvedNode


@dataclass
class ExecutionIR:
    """Fully annotated, resolved process graph ready for runtime execution."""

    process: Process
    resolved_nodes: Dict[str, ResolvedNode]
    resolved_edges: List[ResolvedEdge]
    topological_order: List[str]  # node names in valid execution order

    @property
    def trigger(self) -> ResolvedNode:
        """Return the resolved node that acts as the process entry point."""
        return self.resolved_nodes[self.process.trigger]


# ---------------------------------------------------------------------------
# parse_field_type
# ---------------------------------------------------------------------------

# Regex patterns for each type form.
_RE_ENUM = re.compile(r"^enum\(([^)]+)\)(\?)?$")
_RE_LIST = re.compile(r"^list<([^>]+)>(\?)?$")


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

    # enum(...)  or  enum(...)?
    m = _RE_ENUM.match(type_str)
    if m:
        values_raw, opt_mark = m.group(1), m.group(2)
        values = tuple(v.strip() for v in values_raw.split(","))
        return FieldType(base="enum", optional=bool(opt_mark), enum_values=values)

    # list<...>  or  list<...>?
    m = _RE_LIST.match(type_str)
    if m:
        element, opt_mark = m.group(1).strip(), m.group(2)
        return FieldType(base="list", optional=bool(opt_mark), list_element=element)

    # primitive (may end with ?)
    optional = type_str.endswith("?")
    base = type_str.rstrip("?")
    return FieldType(base=base, optional=optional)


# ---------------------------------------------------------------------------
# resolve_typedef
# ---------------------------------------------------------------------------


def resolve_typedef(name: str, typedef: TypeDef) -> ResolvedTypeDef:
    """Convert a :class:`TypeDef` into a :class:`ResolvedTypeDef`.

    Each field's type string is passed through :func:`parse_field_type`.

    Args:
        name:    The declared name of the type (e.g. ``"BugReport"``).
        typedef: The raw :class:`TypeDef` from the parsed process.

    Returns:
        A :class:`ResolvedTypeDef` with fully parsed field types.
    """
    fields: Dict[str, FieldType] = {}
    for field_name, type_str in typedef.items():
        fields[field_name] = parse_field_type(type_str)
    return ResolvedTypeDef(name=name, fields=fields)


# ---------------------------------------------------------------------------
# Internal: when-expression parser
# ---------------------------------------------------------------------------


class _ParseError(Exception):
    """Internal exception raised by the when-expression tokenizer/parser."""


# Tokenizer -----------------------------------------------------------------

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


def _tokenize(expr: str) -> List[Tuple[str, str]]:
    """Tokenize *expr* into a list of ``(kind, value)`` pairs, skipping WS.

    Raises:
        _ParseError: For any character not matched by the token spec.
    """
    tokens: List[Tuple[str, str]] = []
    pos = 0
    for m in _TOKEN_SPEC.finditer(expr):
        if m.start() != pos:
            # Gap between matches — unrecognized character(s).
            unknown = expr[pos : m.start()]
            raise _ParseError(f"unexpected character(s) {unknown!r}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "WS":
            continue
        tokens.append((kind, m.group()))

    if pos != len(expr):
        unknown = expr[pos:]
        raise _ParseError(f"unexpected character(s) {unknown!r}")

    return tokens


# Recursive-descent parser ---------------------------------------------------
#
# Grammar (left-recursive eliminated, lowest → highest precedence):
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


class _Parser:
    """Recursive-descent parser for BPG ``when`` expressions."""

    def __init__(self, tokens: List[Tuple[str, str]]) -> None:
        self._tokens = tokens
        self._pos = 0

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
            raise _ParseError(f"expected {kind}, got {got}")
        return self._consume()

    def _at_end(self) -> bool:
        return self._pos >= len(self._tokens)

    # -- Grammar rules -----------------------------------------------------

    def parse(self) -> None:
        """Parse the full expression; raise _ParseError on error."""
        self._or_expr()
        if not self._at_end():
            tok = self._peek()
            raise _ParseError(f"unexpected token {tok[1]!r} after expression")

    def _or_expr(self) -> None:
        self._and_expr()
        while self._peek() and self._peek() == ("OP", "||"):
            self._consume()
            self._and_expr()

    def _and_expr(self) -> None:
        self._not_expr()
        while self._peek() and self._peek() == ("OP", "&&"):
            self._consume()
            self._not_expr()

    def _not_expr(self) -> None:
        if self._peek() and self._peek()[0] == "NOT":
            self._consume()
            self._not_expr()
        else:
            self._cmp_expr()

    def _cmp_expr(self) -> None:
        self._primary()
        tok = self._peek()
        if tok and tok[0] == "OP" and tok[1] in {"==", "!=", ">=", "<=", ">", "<"}:
            self._consume()
            self._primary()

    def _primary(self) -> None:
        tok = self._peek()
        if tok is None:
            raise _ParseError("unexpected end of expression")

        kind, value = tok

        # Grouped expression
        if kind == "LPAREN":
            self._consume()
            self._or_expr()
            self._expect("RPAREN")
            return

        # Literals
        if kind in ("STRING", "FLOAT", "INT"):
            self._consume()
            return
        if kind == "WORD" and value in ("true", "false", "null"):
            self._consume()
            return

        # WORD — could be a function call or a path reference
        if kind == "WORD":
            self._consume()
            next_tok = self._peek()
            if next_tok and next_tok[0] == "LPAREN":
                # Function call
                if value not in _KNOWN_FUNCS:
                    raise _ParseError(f"unknown function {value!r}")
                self._consume()  # consume LPAREN
                self._primary()
                self._expect("RPAREN")
            # else: path reference — nothing extra to do
            return

        raise _ParseError(f"unexpected token {value!r}")


def _parse_when(expr: str, src: str, tgt: str) -> None:
    """Validate a single ``when`` expression string.

    Args:
        expr: The raw expression string.
        src:  Source node name (for error messages).
        tgt:  Target node name (for error messages).

    Raises:
        ValidationError: On any syntax error.
    """
    try:
        tokens = _tokenize(expr)
        if not tokens:
            raise _ParseError("empty expression")
        _Parser(tokens).parse()
    except _ParseError as exc:
        raise ValidationError(
            f"Edge {src!r} -> {tgt!r}: invalid when expression: {exc}"
        )


# ---------------------------------------------------------------------------
# Internal: edge mapping type-checker
# ---------------------------------------------------------------------------

# Pattern that identifies a plain field reference: word.word.word
_RE_FIELD_REF = re.compile(r"^[a-zA-Z_]\w*(?:\.[a-zA-Z_]\w*)+$")


def _validate_mapping_ref(
    value: str,
    resolved_nodes: Dict[str, ResolvedNode],
    trigger_name: str,
    src: str,
    tgt: str,
) -> None:
    """Validate a single mapping value (right-hand side of a ``with`` entry).

    String interpolations (``{{...}}``) are skipped.  Plain field refs of the
    form ``node.segment.field`` are validated for node existence; field
    membership is only checked when the referenced node's out_type has a
    non-empty field set (structured typedef).

    Args:
        value:          The mapping value string.
        resolved_nodes: All resolved nodes keyed by name.
        trigger_name:   The process trigger node name (alias ``"trigger"``).
        src:            Source node name (for error messages).
        tgt:            Target node name (for error messages).

    Raises:
        ValidationError: If the referenced node does not exist in the process.
    """
    # String interpolation — skip
    if "{{" in value:
        return

    # Must look like a dotted path to be a field ref
    if not _RE_FIELD_REF.match(value):
        return

    parts = value.split(".")
    node_ref = parts[0]

    # Resolve "trigger" alias
    if node_ref == "trigger":
        node_ref = trigger_name

    if node_ref not in resolved_nodes:
        raise ValidationError(
            f"Edge {src!r} -> {tgt!r}: with mapping references unknown node {node_ref!r}"
        )

    # If there are more than two parts (node.segment.field), we can check the
    # field against the referenced type if it's structured.
    if len(parts) >= 3:
        segment = parts[1]  # e.g. "out" or "in"
        field_name = parts[2]
        rnode = resolved_nodes[node_ref]

        # Choose which typedef to inspect
        ref_type: Optional[ResolvedTypeDef] = None
        if segment == "out":
            ref_type = rnode.out_type
        elif segment == "in":
            ref_type = rnode.in_type

        if ref_type is not None and ref_type.fields:
            # Only raise when the field is definitively absent from a structured type
            if field_name not in ref_type.fields:
                raise ValidationError(
                    f"Edge {src!r} -> {tgt!r}: with mapping references unknown field "
                    f"{field_name!r} on {node_ref}.{segment}"
                )


def _typecheck_edge_mappings(
    process: Process,
    resolved_nodes: Dict[str, ResolvedNode],
) -> None:
    """Type-check all edge ``with`` mappings against their target node's ``in`` schema.

    Checks performed per edge:
      - Extra fields (present in mapping but absent from target schema).
      - Missing required fields (absent from mapping but required by schema).
      - Field ref validity for each mapping value.

    Args:
        process:        The validated process.
        resolved_nodes: Resolved nodes keyed by name.

    Raises:
        ValidationError: On the first type mismatch or reference error found.
    """
    trigger_name = process.trigger

    for edge in process.edges:
        if edge.mapping is None:
            continue

        src, tgt = edge.source, edge.target
        target_node = resolved_nodes[tgt]
        in_type = target_node.in_type

        # Primitive in-type → no schema to check against; only validate refs
        if not in_type.fields:
            for value in edge.mapping.values():
                _validate_mapping_ref(value, resolved_nodes, trigger_name, src, tgt)
            continue

        mapping_keys = set(edge.mapping.keys())
        schema_keys = set(in_type.fields.keys())
        required_keys = set(in_type.required_fields())

        # Extra fields not declared in target schema
        extra = sorted(mapping_keys - schema_keys)
        if extra:
            raise ValidationError(
                f"Edge {src!r} -> {tgt!r}: with mapping contains fields not in "
                f"target schema: {extra}"
            )

        # Missing required fields
        missing = sorted(required_keys - mapping_keys)
        if missing:
            raise ValidationError(
                f"Edge {src!r} -> {tgt!r}: with mapping is missing required fields: "
                f"{missing}"
            )

        # Validate each mapping value
        for value in edge.mapping.values():
            _validate_mapping_ref(value, resolved_nodes, trigger_name, src, tgt)


# ---------------------------------------------------------------------------
# Internal: when-expression batch validator
# ---------------------------------------------------------------------------


def _validate_when_expressions(process: Process) -> None:
    """Validate every edge ``when`` expression in the process.

    Args:
        process: The validated process.

    Raises:
        ValidationError: On the first invalid ``when`` expression.
    """
    for edge in process.edges:
        if edge.when is not None:
            _parse_when(edge.when, edge.source, edge.target)


# ---------------------------------------------------------------------------
# Internal: topological sort (Kahn's algorithm)
# ---------------------------------------------------------------------------


def _topological_sort(process: Process) -> List[str]:
    """Produce a valid execution order for process nodes using Kahn's algorithm.

    Determinism is maintained by iterating in the original declaration order of
    ``process.nodes`` when selecting the next zero-in-degree node.

    Args:
        process: The validated (acyclic) process.

    Returns:
        A list of node names in topological order.

    Raises:
        ValidationError: If a cycle is detected (should not occur after
            ``validate_process`` has been called successfully).
    """
    # Build adjacency and in-degree structures
    adj: Dict[str, List[str]] = {name: [] for name in process.nodes}
    in_degree: Dict[str, int] = {name: 0 for name in process.nodes}

    for edge in process.edges:
        adj[edge.source].append(edge.target)
        in_degree[edge.target] += 1

    # Preserve declaration order for determinism — only used as a source of
    # candidates; deque is drained with popleft (FIFO).
    node_order = list(process.nodes.keys())

    # Seed queue with zero-in-degree nodes in declaration order
    queue: deque[str] = deque(
        name for name in node_order if in_degree[name] == 0
    )
    order: List[str] = []

    while queue:
        node = queue.popleft()
        order.append(node)
        for neighbour in adj[node]:
            in_degree[neighbour] -= 1
            if in_degree[neighbour] == 0:
                # Insert in declaration order relative to other newly-zero nodes
                # by appending; full declaration-order re-sort is not required
                # because Kahn's queue naturally respects dependency ordering.
                queue.append(neighbour)

    if len(order) != len(process.nodes):
        raise ValidationError("Cycle detected during topological sort")

    return order


# ---------------------------------------------------------------------------
# Public: compile_process
# ---------------------------------------------------------------------------


def compile_process(process: Process) -> ExecutionIR:
    """Compile a validated :class:`Process` into an :class:`ExecutionIR`.

    This function assumes :func:`~bpg.compiler.validator.validate_process` has
    already been called successfully.  It performs:

    1. Build type registry — resolve all ``process.types`` entries.
    2. Resolve all nodes — attach parsed in/out types to each node instance.
    3. Type-check edge ``with`` mappings.
    4. Validate ``when`` expressions.
    5. Topological sort.
    6. Build ``resolved_edges`` list.
    7. Return ``ExecutionIR``.

    Args:
        process: A structurally-valid, semantically-validated :class:`Process`.

    Returns:
        An :class:`ExecutionIR` ready for runtime execution.

    Raises:
        ValidationError: If any type-checking or expression validation fails.
    """
    # Step 1: Build type registry
    type_registry: Dict[str, ResolvedTypeDef] = {}
    for type_name, typedef in process.types.items():
        type_registry[type_name] = resolve_typedef(type_name, typedef)

    # Helper: resolve a type name to a ResolvedTypeDef
    def _resolve_type(type_name: str) -> ResolvedTypeDef:
        if type_name in type_registry:
            return type_registry[type_name]
        # Primitive / unknown-but-validated type → empty field set
        return ResolvedTypeDef(name=type_name, fields={})

    # Step 2: Resolve all nodes
    resolved_nodes: Dict[str, ResolvedNode] = {}
    for node_name, node_instance in process.nodes.items():
        node_type = process.node_types[node_instance.node_type]
        in_type = _resolve_type(node_type.input_type)
        out_type = _resolve_type(node_type.output_type)
        resolved_nodes[node_name] = ResolvedNode(
            name=node_name,
            instance=node_instance,
            node_type=node_type,
            in_type=in_type,
            out_type=out_type,
        )

    # Step 3: Type-check edge with mappings
    _typecheck_edge_mappings(process, resolved_nodes)

    # Step 4: Validate when expressions
    _validate_when_expressions(process)

    # Step 5: Topological sort
    topological_order = _topological_sort(process)

    # Step 6: Build resolved_edges
    resolved_edges: List[ResolvedEdge] = [
        ResolvedEdge(
            edge=edge,
            source=resolved_nodes[edge.source],
            target=resolved_nodes[edge.target],
        )
        for edge in process.edges
    ]

    # Step 7: Return IR
    return ExecutionIR(
        process=process,
        resolved_nodes=resolved_nodes,
        resolved_edges=resolved_edges,
        topological_order=topological_order,
    )
