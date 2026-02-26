from __future__ import annotations

from pathlib import Path
import re

import yaml

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_FILE = REPO_ROOT / "docs" / "bpg-spec.md"
CANONICAL_PROCESS_FILE = REPO_ROOT / "process.bpg.yaml"


def _extract_named_yaml_blocks(markdown: str) -> dict[str, str]:
    section_header = "## 16. Full Example: Bug Triage Process"
    start = markdown.find(section_header)
    assert start != -1, "Spec is missing the full-example section."
    section = markdown[start:]

    blocks: dict[str, str] = {}
    for match in re.finditer(r"```yaml\n(.*?)\n```", section, re.DOTALL):
        block = match.group(1)
        lines = block.splitlines()
        first_nonempty = next((line.strip() for line in lines if line.strip()), "")
        if first_nonempty.startswith("#"):
            name = first_nonempty.lstrip("#").strip()
            blocks[name] = "\n".join(lines[1:]).strip() + "\n"
    return blocks


def test_spec_examples_compile_and_match_runtime_process(tmp_path: Path):
    markdown = SPEC_FILE.read_text()
    blocks = _extract_named_yaml_blocks(markdown)

    required = ("types.bpg.yaml", "node_types.bpg.yaml", "process.bpg.yaml")
    for name in required:
        assert name in blocks, f"Missing required example block in spec: {name}"

    types_doc = yaml.safe_load(blocks["types.bpg.yaml"])
    node_types_doc = yaml.safe_load(blocks["node_types.bpg.yaml"])
    process_doc = yaml.safe_load(blocks["process.bpg.yaml"])

    assert isinstance(types_doc, dict) and "types" in types_doc
    assert isinstance(node_types_doc, dict) and "node_types" in node_types_doc
    assert isinstance(process_doc, dict)

    merged = dict(process_doc)
    merged["types"] = types_doc["types"]
    merged["node_types"] = node_types_doc["node_types"]

    assembled_path = tmp_path / "spec-example.process.bpg.yaml"
    assembled_path.write_text(yaml.safe_dump(merged, sort_keys=False))

    spec_process = parse_process_file(assembled_path)
    validate_process(spec_process)
    spec_ir = compile_process(spec_process)

    canonical_process = parse_process_file(CANONICAL_PROCESS_FILE)
    validate_process(canonical_process)
    canonical_ir = compile_process(canonical_process)

    assert set(spec_process.nodes.keys()) == set(canonical_process.nodes.keys())
    assert spec_process.trigger == canonical_process.trigger
    assert spec_process.output == canonical_process.output
    assert set(spec_process.types.keys()) == set(canonical_process.types.keys())
    assert set(spec_process.node_types.keys()) == set(canonical_process.node_types.keys())
    assert {
        (edge.source, edge.target) for edge in spec_process.edges
    } == {(edge.source, edge.target) for edge in canonical_process.edges}

    assert set(spec_ir.resolved_nodes.keys()) == set(canonical_ir.resolved_nodes.keys())
    assert {(e.source.name, e.target.name) for e in spec_ir.resolved_edges} == {
        (e.source.name, e.target.name) for e in canonical_ir.resolved_edges
    }
