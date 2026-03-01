from __future__ import annotations

from pathlib import Path
import re

from bpg.compiler.ir import compile_process
from bpg.compiler.parser import parse_process_file
from bpg.compiler.validator import validate_process


REPO_ROOT = Path(__file__).resolve().parents[2]
MANUAL_EXAMPLES_FILE = REPO_ROOT / "manual" / "nodes" / "examples.md"


def _extract_yaml_blocks(markdown: str) -> list[str]:
    blocks: list[str] = []
    for match in re.finditer(r"```yaml\n(.*?)\n```", markdown, re.DOTALL):
        block = match.group(1).strip()
        if block:
            blocks.append(block + "\n")
    return blocks


def test_manual_node_examples_compile(tmp_path: Path) -> None:
    markdown = MANUAL_EXAMPLES_FILE.read_text(encoding="utf-8")
    blocks = _extract_yaml_blocks(markdown)
    assert len(blocks) >= 1, "manual/nodes/examples.md must contain at least one YAML block."

    for idx, block in enumerate(blocks, start=1):
        process_file = tmp_path / f"manual-example-{idx}.process.bpg.yaml"
        process_file.write_text(block, encoding="utf-8")
        process = parse_process_file(process_file)
        validate_process(process)
        compile_process(process)
