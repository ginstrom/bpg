"""Tests that verify the structure and validity of framework examples (step 09)."""
from __future__ import annotations

from pathlib import Path

import yaml

from bpg.compiler.parser import parse_process_spec_v2_file
from bpg.compiler.spec_v2 import compile_process_spec_v2, validate_process_spec_v2


REPO_ROOT = Path(__file__).resolve().parents[2]
EXAMPLES_DIR = REPO_ROOT / "examples"


# ---------------------------------------------------------------------------
# core/parse-sum
# ---------------------------------------------------------------------------


def test_core_parse_sum_v2_spec_exists() -> None:
    spec = EXAMPLES_DIR / "core" / "parse-sum" / "process.v2.bpg.yaml"
    assert spec.exists(), f"Expected example spec at {spec}"


def test_core_parse_sum_v2_spec_has_schema_version_2() -> None:
    spec_path = EXAMPLES_DIR / "core" / "parse-sum" / "process.v2.bpg.yaml"
    raw = yaml.safe_load(spec_path.read_text())
    assert raw.get("schema_version") == 2


def test_core_parse_sum_uses_only_node_package_refs() -> None:
    spec_path = EXAMPLES_DIR / "core" / "parse-sum" / "process.v2.bpg.yaml"
    raw = yaml.safe_load(spec_path.read_text())
    for node_id, node_def in raw["process"]["nodes"].items():
        assert "ref" in node_def, f"Node {node_id!r} missing 'ref'"
        assert "package" in node_def["ref"], f"Node {node_id!r} ref missing 'package'"
        assert node_def["ref"]["package"].startswith("bpg.nodes."), (
            f"Node {node_id!r} ref package should start with 'bpg.nodes.'"
        )


def test_core_parse_sum_v2_spec_parses_and_validates() -> None:
    spec_path = EXAMPLES_DIR / "core" / "parse-sum" / "process.v2.bpg.yaml"
    spec = parse_process_spec_v2_file(spec_path)
    validate_process_spec_v2(spec)


def test_core_parse_sum_v2_spec_compiles() -> None:
    spec_path = EXAMPLES_DIR / "core" / "parse-sum" / "process.v2.bpg.yaml"
    spec = parse_process_spec_v2_file(spec_path)
    result = compile_process_spec_v2(spec)
    assert result.execution_plan.process_name == "parse-sum"
    node_ids = {n.node_id for n in result.execution_plan.nodes}
    assert "ingest" in node_ids
    assert "parse" in node_ids
    assert "sum" in node_ids


def test_core_parse_sum_readme_exists() -> None:
    readme = EXAMPLES_DIR / "core" / "parse-sum" / "README.md"
    assert readme.exists(), f"Expected README at {readme}"


def test_core_parse_sum_input_yaml_exists() -> None:
    input_file = EXAMPLES_DIR / "core" / "parse-sum" / "input.yaml"
    assert input_file.exists(), f"Expected input.yaml at {input_file}"


# ---------------------------------------------------------------------------
# release versioning docs
# ---------------------------------------------------------------------------


def test_release_versioning_doc_exists() -> None:
    doc = REPO_ROOT / "docs" / "framework" / "release-versioning.md"
    assert doc.exists(), f"Expected release versioning doc at {doc}"


def test_release_versioning_doc_covers_framework_and_node_packages() -> None:
    doc = REPO_ROOT / "docs" / "framework" / "release-versioning.md"
    content = doc.read_text()
    assert "framework" in content.lower()
    assert "node" in content.lower()
    assert "version" in content.lower()


def test_release_versioning_doc_mentions_cutover_version() -> None:
    doc = REPO_ROOT / "docs" / "framework" / "release-versioning.md"
    content = doc.read_text()
    assert "0.1.0" in content
