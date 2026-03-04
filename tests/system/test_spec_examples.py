from __future__ import annotations

from pathlib import Path

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process


REPO_ROOT = Path(__file__).resolve().parents[2]
CANONICAL_PROCESS_FILE = REPO_ROOT / "process.bpg.yaml"


def test_canonical_process_compiles_and_has_expected_shape():
    process = parse_process_file(CANONICAL_PROCESS_FILE)
    validate_process(process)
    ir = compile_process(process)

    assert process.metadata.name == "bug-triage-process"
    assert process.trigger == "intake_form"
    assert process.output == "gitlab.out.ticket_id"
    assert set(process.nodes.keys()) == {
        "intake_form",
        "triage",
        "approval",
        "gitlab",
    }
    assert {(edge.source, edge.target) for edge in process.edges} == {
        ("intake_form", "triage"),
        ("triage", "approval"),
        ("triage", "gitlab"),
        ("approval", "gitlab"),
    }

    assert set(ir.resolved_nodes.keys()) == set(process.nodes.keys())
    assert {(e.source.name, e.target.name) for e in ir.resolved_edges} == {
        (edge.source, edge.target) for edge in process.edges
    }
