import pytest
from pathlib import Path
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process
from bpg.compiler.ir import compile_process
from bpg.compiler.visualizer import generate_html
from bpg.models.schema import Edge, NodeInstance, NodeType, Process, ProcessMetadata


def test_generate_html():
    process_file = Path("process.bpg.yaml")
    process = parse_process_file(process_file)
    validate_process(process)
    ir = compile_process(process)
    html = generate_html(ir)

    assert "BPG Visualizer" in html
    assert "bug-triage-process" in html
    assert "intake_form" in html
    assert "triage" in html
    assert "approval" in html
    assert "gitlab" in html
    assert "<svg" in html
    assert "TRIGGER" in html


def _make_process():
    return Process(
        metadata=ProcessMetadata(name="viz-test", version="1.0"),
        types={},
        node_types={
            "worker@v1": NodeType(**{"in": "object", "out": "object", "provider": "test"}),
        },
        nodes={
            "start": NodeInstance(**{"type": "worker@v1"}),
            "finish": NodeInstance(**{"type": "worker@v1"}),
        },
        edges=[Edge(**{"from": "start", "to": "finish"})],
        trigger="start",
    )


def test_generate_html_smoke():
    p = _make_process()
    validate_process(p)
    ir = compile_process(p)
    html = generate_html(ir)
    assert html.startswith("<!DOCTYPE html>")
    assert "start" in html
    assert "finish" in html
    assert "viz-test" in html
