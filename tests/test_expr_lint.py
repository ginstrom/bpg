from __future__ import annotations

import pytest

from bpg.compiler.expr_lint import ExprLintError, lint_when_expression
from bpg.compiler.validator import ValidationError, validate_process
from bpg.models.schema import Edge, NodeInstance, NodeType, Process, TypeDef


def _process_with_when(expr: str) -> Process:
    return Process(
        types={
            "InType": TypeDef(root={"a": "string"}),
            "OutType": TypeDef(root={"result": "string"}),
        },
        node_types={
            "worker@v1": NodeType(
                **{"in": "InType", "out": "OutType", "provider": "mock", "version": "v1"}
            ),
        },
        nodes={
            "trigger_node": NodeInstance(**{"type": "worker@v1"}),
            "worker_node": NodeInstance(**{"type": "worker@v1"}),
        },
        edges=[
            Edge(
                **{
                    "from": "trigger_node",
                    "to": "worker_node",
                    "when": expr,
                    "with": {"a": "trigger_node.out.result"},
                }
            )
        ],
        trigger="trigger_node",
    )


def test_lint_reports_unknown_function_with_code_and_column():
    with pytest.raises(ExprLintError) as excinfo:
        lint_when_expression("forbidden_func(x.out.val)")
    err = excinfo.value
    assert err.code == "E_EXPR_UNKNOWN_FUNCTION"
    assert err.column == 1


def test_lint_reports_unexpected_character_position():
    with pytest.raises(ExprLintError) as excinfo:
        lint_when_expression("x # y")
    err = excinfo.value
    assert err.code == "E_EXPR_TOKEN_UNEXPECTED_CHAR"
    assert err.column == 3


def test_validator_when_error_has_expr_code_path_and_column():
    process = _process_with_when("x # y")
    with pytest.raises(ValidationError, match="invalid when expression") as excinfo:
        validate_process(process)
    diag = excinfo.value.diagnostic.to_dict()
    assert diag["error_code"] == "E_EXPR_TOKEN_UNEXPECTED_CHAR"
    assert diag["path"] == "$.edges[0].when"
    assert diag["schema_excerpt"]["column"] == 3
