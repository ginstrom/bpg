"""Tests for the first-party BPG node packages (step 7).

Covers:
- Package install tests in clean virtualenvs
- Discovery across multiple installed node packages
- Marketplace metadata generation for each first-party package
- Example workflow v2 compilation using only installed packages
"""

from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from importlib.metadata import EntryPoint
from pathlib import Path
from typing import Any

import pytest

from bpg.compiler.parser import parse_process_spec_v2_file
from bpg.compiler.spec_v2 import compile_process_spec_v2, validate_process_spec_v2
from bpg_sdk.discovery import DiscoveredNode, discover_nodes
from bpg_sdk.manifest import NodeManifest
from bpg_sdk.marketplace import export_catalog, export_node_manifest, validate_artifacts


REPO_ROOT = Path(__file__).resolve().parents[2]
BPG_SDK_PACKAGE = REPO_ROOT / "packages" / "bpg-sdk"

_FIRST_PARTY_PACKAGES = [
    ("bpg-nodes-core", "bpg.nodes.core@v1", REPO_ROOT / "packages" / "bpg-nodes-core"),
    ("bpg-nodes-ai", "bpg.nodes.ai@v1", REPO_ROOT / "packages" / "bpg-nodes-ai"),
    ("bpg-nodes-human", "bpg.nodes.human@v1", REPO_ROOT / "packages" / "bpg-nodes-human"),
    ("bpg-nodes-search", "bpg.nodes.search@v1", REPO_ROOT / "packages" / "bpg-nodes-search"),
    ("bpg-nodes-comm", "bpg.nodes.comm@v1", REPO_ROOT / "packages" / "bpg-nodes-comm"),
]

_EXPECTED_NODES_BY_PACKAGE: dict[str, list[str]] = {
    "bpg.nodes.core@v1": [
        "passthrough",
        "dataset.select_rows",
        "csv.read",
        "flow.loop",
        "flow.fanout",
        "flow.await_all",
        "timer.delay",
        "process_call",
        "fs.markdown_list",
        "text.markdown_chunk",
        "text.parse_numbers",
        "math.sum_numbers",
    ],
    "bpg.nodes.ai@v1": ["anthropic", "openai", "google", "ollama", "llm"],
    "bpg.nodes.human@v1": ["dashboard.form", "agent.pipeline"],
    "bpg.nodes.search@v1": ["embed.text", "weaviate.upsert", "weaviate.hybrid_search", "web_search"],
    "bpg.nodes.comm@v1": [
        "notify.email",
        "http.gitlab",
        "queue.kafka",
        "slack.interactive",
        "http.webhook",
    ],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_entry_points_for_packages(
    *package_ids: str,
    catalog: dict[tuple[str, str], DiscoveredNode],
) -> list[EntryPoint]:
    import types
    import sys as _sys

    eps: list[EntryPoint] = []
    for (pkg_id, node_id), discovered in catalog.items():
        if pkg_id not in package_ids:
            continue
        module_name = f"_test_fp_{pkg_id.replace('.', '_').replace('@', '_')}_{node_id.replace('.', '_')}"
        module = types.ModuleType(module_name)
        setattr(module, node_id.replace(".", "_"), discovered.implementation)
        _sys.modules[module_name] = module
        ep_name = node_id
        attr = node_id.replace(".", "_")
        eps.append(EntryPoint(name=ep_name, value=f"{module_name}:{attr}", group="bpg.nodes"))
    return eps


# ---------------------------------------------------------------------------
# Node presence tests (import-time, no external calls)
# ---------------------------------------------------------------------------

def test_bpg_nodes_core_manifest_fields() -> None:
    from bpg_nodes_core import passthrough, flow_loop, text_parse_numbers, math_sum_numbers

    assert passthrough.manifest.package == "bpg.nodes.core@v1"
    assert passthrough.manifest.node_id == "passthrough"

    assert flow_loop.manifest.node_id == "flow.loop"
    assert text_parse_numbers.manifest.node_id == "text.parse_numbers"
    assert math_sum_numbers.manifest.node_id == "math.sum_numbers"


def test_bpg_nodes_core_passthrough_run() -> None:
    from bpg_nodes_core import passthrough

    result = passthrough.run({"key": "value", "num": 42})
    assert result == {"key": "value", "num": 42}


def test_bpg_nodes_core_flow_loop() -> None:
    from bpg_nodes_core import flow_loop

    result = flow_loop.run({"items": [1, 2, 3, 4, 5], "max_iterations": 3})
    assert result == {"items": [1, 2, 3], "count": 3, "truncated": True}


def test_bpg_nodes_core_flow_fanout() -> None:
    from bpg_nodes_core import flow_fanout

    result = flow_fanout.run({"items": ["a", "b"]})
    assert result["count"] == 2
    assert result["branches"][0] == {"index": 0, "item": "a"}


def test_bpg_nodes_core_flow_await_all() -> None:
    from bpg_nodes_core import flow_await_all

    result = flow_await_all.run({"results": [{"x": 1}, {"x": 2}]})
    assert result == {"results": [{"x": 1}, {"x": 2}], "count": 2}


def test_bpg_nodes_core_text_parse_numbers() -> None:
    from bpg_nodes_core import text_parse_numbers

    result = text_parse_numbers.run({"text": "sum is 3.14 and count is 10"})
    assert result["numbers"] == [3.14, 10.0]


def test_bpg_nodes_core_math_sum_numbers() -> None:
    from bpg_nodes_core import math_sum_numbers

    result = math_sum_numbers.run({"numbers": [1.0, 2.0, 3.5]})
    assert result == {"sum": 6.5, "count": 3}


def test_bpg_nodes_core_dataset_select_rows() -> None:
    from bpg_nodes_core import dataset_select_rows

    rows = [{"row_id": 1, "name": "Alice"}, {"row_id": 2, "name": "Bob"}]
    result = dataset_select_rows.run({"rows": rows, "row_ids": [1]})
    assert result == {"rows": [{"row_id": 1, "name": "Alice"}]}


def test_bpg_nodes_core_timer_delay_zero() -> None:
    from bpg_nodes_core import timer_delay

    result = timer_delay.run({"duration": 0})
    assert result == {"ok": True, "slept_seconds": 0.0}


def test_bpg_nodes_human_dashboard_form() -> None:
    from bpg_nodes_human import dashboard_form

    assert dashboard_form.manifest.package == "bpg.nodes.human@v1"
    result = dashboard_form.run({"defaults": {"color": "blue"}, "color": "red"})
    assert result["color"] == "red"


def test_bpg_nodes_human_agent_pipeline_low_risk() -> None:
    from bpg_nodes_human import agent_pipeline

    result = agent_pipeline.run({"title": "Minor bug", "severity": "S3"})
    assert result["risk"] == "low"
    assert result["summary"] == "Minor bug"


def test_bpg_nodes_human_agent_pipeline_high_risk() -> None:
    from bpg_nodes_human import agent_pipeline

    result = agent_pipeline.run({"title": "Production outage", "severity": "P0"})
    assert result["risk"] == "high"


def test_bpg_nodes_human_agent_pipeline_mock_output() -> None:
    from bpg_nodes_human import agent_pipeline

    result = agent_pipeline.run({"mock_output": {"risk": "custom", "summary": "test"}})
    assert result == {"risk": "custom", "summary": "test"}


def test_bpg_nodes_search_embed_text_chunks() -> None:
    from bpg_nodes_search import embed_text

    assert embed_text.manifest.package == "bpg.nodes.search@v1"
    chunks = [
        {"source_id": "abc", "chunk_id": "abc:0", "text": "hello world", "metadata": {}},
    ]
    result = embed_text.run({"chunks": chunks})
    assert "items" in result
    assert len(result["items"]) == 1
    assert len(result["items"][0]["vector"]) == 16


def test_bpg_nodes_search_embed_text_query() -> None:
    from bpg_nodes_search import embed_text

    result = embed_text.run({"query": "test query", "top_k": 5})
    assert result["query"] == "test query"
    assert len(result["vector"]) == 16
    assert result["top_k"] == 5


def test_bpg_nodes_search_weaviate_upsert_and_search(tmp_path: Path) -> None:
    from bpg_nodes_search import embed_text, weaviate_upsert, weaviate_hybrid_search

    store_path = str(tmp_path / "search.jsonl")
    chunks = [{"source_id": "s1", "chunk_id": "s1:0", "text": "Python programming", "metadata": {}}]
    embedded = embed_text.run({"chunks": chunks})

    upsert_result = weaviate_upsert.run({"items": embedded["items"], "store_path": store_path})
    assert upsert_result["inserted"] == 1
    assert upsert_result["failed"] == 0

    query_result = embed_text.run({"query": "Python"})
    search_result = weaviate_hybrid_search.run({
        "query": "Python",
        "vector": query_result["vector"],
        "top_k": 3,
        "store_path": store_path,
    })
    assert search_result["query"] == "Python"
    assert len(search_result["hits"]) == 1
    assert "Python" in search_result["hits"][0]["text"]


def test_bpg_nodes_search_web_search_dry_run() -> None:
    from bpg_nodes_search import web_search

    result = web_search.run({"query": "test search", "top_k": 3, "dry_run": True})
    assert result["source"] == "dry-run"
    assert len(result["results"]) == 3


def test_bpg_nodes_comm_notify_email_dry_run() -> None:
    from bpg_nodes_comm import notify_email

    assert notify_email.manifest.package == "bpg.nodes.comm@v1"
    result = notify_email.run({
        "to": "user@example.com",
        "subject": "Test",
        "body": "Hello",
        "from_addr": "robot@example.com",
        "dry_run": True,
    })
    assert result["sent"] is False
    assert result["dry_run"] is True
    assert result["to"] == "user@example.com"


def test_bpg_nodes_comm_http_gitlab() -> None:
    from bpg_nodes_comm import http_gitlab

    result = http_gitlab.run({"ticket_prefix": "TEST"})
    assert result["ticket_id"].startswith("TEST-")
    assert "gitlab.local" in result["url"]


def test_bpg_nodes_comm_queue_kafka() -> None:
    from bpg_nodes_comm import queue_kafka

    result = queue_kafka.run({"topic": "events", "partition": 2})
    assert result["published"] is True
    assert result["topic"] == "events"
    assert result["partition"] == 2


def test_bpg_nodes_comm_slack_interactive_dry_run() -> None:
    from bpg_nodes_comm import slack_interactive

    result = slack_interactive.run({"channel": "#test", "dry_run": True})
    assert result["dispatched"] is True
    assert result["dry_run"] is True
    assert result["channel"] == "#test"


def test_bpg_nodes_ai_manifest_fields() -> None:
    from bpg_nodes_ai import anthropic, google, openai, ollama, llm

    for node_func, expected_id in [
        (anthropic, "anthropic"),
        (google, "google"),
        (openai, "openai"),
        (ollama, "ollama"),
        (llm, "llm"),
    ]:
        assert node_func.manifest.package == "bpg.nodes.ai@v1"
        assert node_func.manifest.node_id == expected_id


def test_bpg_nodes_ai_dry_run() -> None:
    from bpg_nodes_ai import anthropic

    result = anthropic.run({
        "model": "claude-3-haiku-20240307",
        "dry_run": True,
        "mock_output": {"answer": "42"},
    })
    assert result == {"answer": "42"}


# ---------------------------------------------------------------------------
# Discovery tests across multiple packages
# ---------------------------------------------------------------------------

def test_discover_all_first_party_packages() -> None:
    """All first-party node packages are discovered together via entry points."""
    catalog = discover_nodes()

    for package_id, expected_node_ids in _EXPECTED_NODES_BY_PACKAGE.items():
        for node_id in expected_node_ids:
            key = (package_id, node_id)
            assert key in catalog, f"Expected {package_id}:{node_id} in catalog"
            assert catalog[key].manifest.package == package_id
            assert catalog[key].manifest.node_id == node_id


def test_discovery_catalog_has_expected_total_count() -> None:
    catalog = discover_nodes()
    total = sum(len(ids) for ids in _EXPECTED_NODES_BY_PACKAGE.values())
    assert len(catalog) >= total


def test_discovery_manifests_are_valid() -> None:
    catalog = discover_nodes()
    for (package_id, node_id), discovered in catalog.items():
        manifest = discovered.manifest
        assert manifest.package == package_id
        assert manifest.node_id == node_id
        assert manifest.package.startswith("bpg.nodes.")
        assert "@v" in manifest.package


# ---------------------------------------------------------------------------
# Marketplace metadata generation tests
# ---------------------------------------------------------------------------

def test_marketplace_export_for_all_first_party_packages() -> None:
    catalog = discover_nodes()
    artifacts = export_catalog(catalog.values())
    errors = validate_artifacts(artifacts)
    assert errors == [], f"Marketplace validation errors: {errors}"


def test_marketplace_artifacts_cover_all_packages() -> None:
    catalog = discover_nodes()
    artifacts = export_catalog(catalog.values())
    artifact_packages = {a.package_id for a in artifacts}
    for package_id in _EXPECTED_NODES_BY_PACKAGE:
        assert package_id in artifact_packages, f"{package_id} missing from marketplace artifacts"


def test_marketplace_install_spec_derived_correctly() -> None:
    catalog = discover_nodes()
    artifacts = export_catalog(catalog.values())

    expected_package_names = {
        "bpg.nodes.core@v1": "bpg-nodes-core",
        "bpg.nodes.ai@v1": "bpg-nodes-ai",
        "bpg.nodes.human@v1": "bpg-nodes-human",
        "bpg.nodes.search@v1": "bpg-nodes-search",
        "bpg.nodes.comm@v1": "bpg-nodes-comm",
    }
    for artifact in artifacts:
        if artifact.package_id in expected_package_names:
            expected = expected_package_names[artifact.package_id]
            assert artifact.install.package_name == expected, (
                f"{artifact.package_id}: expected package name {expected!r}, "
                f"got {artifact.install.package_name!r}"
            )
            assert artifact.install.uv == f"uv add {expected}"
            assert artifact.install.pip == f"pip install {expected}"


def test_marketplace_artifacts_written_to_disk(tmp_path: Path) -> None:
    from bpg_sdk.marketplace import write_artifacts, load_artifact

    catalog = discover_nodes()
    artifacts = export_catalog(catalog.values())
    written = write_artifacts(artifacts, tmp_path)

    assert len(written) == len(artifacts)
    for path in written:
        assert path.exists()
        loaded = load_artifact(path)
        assert loaded.artifact_version == "1"
        assert loaded.package_id.startswith("bpg.nodes.")


# ---------------------------------------------------------------------------
# Example workflow v2 compilation tests
# ---------------------------------------------------------------------------

def _write_v2_process(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "process.v2.bpg.yaml"
    path.write_text(content.strip() + "\n", encoding="utf-8")
    return path


def test_v2_process_compiles_with_core_nodes(tmp_path: Path) -> None:
    process_file = _write_v2_process(
        tmp_path,
        textwrap.dedent("""
            schema_version: 2
            process:
              name: parse_sum
              trigger: start
              nodes:
                start:
                  ref:
                    package: bpg.nodes.core@v1
                    node: passthrough
                parse:
                  ref:
                    package: bpg.nodes.core@v1
                    node: text.parse_numbers
                sum:
                  ref:
                    package: bpg.nodes.core@v1
                    node: math.sum_numbers
              edges:
                - from: start
                  to: parse
                - from: parse
                  to: sum
        """),
    )
    catalog = discover_nodes()
    node_catalog = {key: d.manifest for key, d in catalog.items()}
    spec = parse_process_spec_v2_file(process_file)
    validate_process_spec_v2(spec, node_catalog=node_catalog)
    compiled = compile_process_spec_v2(spec, node_catalog=node_catalog)

    node_ids = {n.package_node_id for n in compiled.execution_plan.nodes}
    assert "passthrough" in node_ids
    assert "text.parse_numbers" in node_ids
    assert "math.sum_numbers" in node_ids


def test_v2_process_compiles_with_search_nodes(tmp_path: Path) -> None:
    process_file = _write_v2_process(
        tmp_path,
        textwrap.dedent("""
            schema_version: 2
            process:
              name: search_ingest
              trigger: start
              nodes:
                start:
                  ref:
                    package: bpg.nodes.core@v1
                    node: fs.markdown_list
                chunk:
                  ref:
                    package: bpg.nodes.core@v1
                    node: text.markdown_chunk
                embed:
                  ref:
                    package: bpg.nodes.search@v1
                    node: embed.text
                upsert:
                  ref:
                    package: bpg.nodes.search@v1
                    node: weaviate.upsert
              edges:
                - from: start
                  to: chunk
                - from: chunk
                  to: embed
                - from: embed
                  to: upsert
        """),
    )
    catalog = discover_nodes()
    node_catalog = {key: d.manifest for key, d in catalog.items()}
    spec = parse_process_spec_v2_file(process_file)
    validate_process_spec_v2(spec, node_catalog=node_catalog)
    compiled = compile_process_spec_v2(spec, node_catalog=node_catalog)

    packages = {n.package_id for n in compiled.execution_plan.nodes}
    assert "bpg.nodes.core@v1" in packages
    assert "bpg.nodes.search@v1" in packages


def test_v2_process_compiles_with_ai_and_comm_nodes(tmp_path: Path) -> None:
    process_file = _write_v2_process(
        tmp_path,
        textwrap.dedent("""
            schema_version: 2
            process:
              name: ai_notify
              trigger: ingest
              nodes:
                ingest:
                  ref:
                    package: bpg.nodes.core@v1
                    node: csv.read
                enrich:
                  ref:
                    package: bpg.nodes.ai@v1
                    node: google
                notify:
                  ref:
                    package: bpg.nodes.comm@v1
                    node: notify.email
              edges:
                - from: ingest
                  to: enrich
                - from: enrich
                  to: notify
        """),
    )
    catalog = discover_nodes()
    node_catalog = {key: d.manifest for key, d in catalog.items()}
    spec = parse_process_spec_v2_file(process_file)
    validate_process_spec_v2(spec, node_catalog=node_catalog)
    compiled = compile_process_spec_v2(spec, node_catalog=node_catalog)

    packages = {n.package_id for n in compiled.execution_plan.nodes}
    assert "bpg.nodes.ai@v1" in packages
    assert "bpg.nodes.comm@v1" in packages


def test_v2_process_rejects_unknown_node_id(tmp_path: Path) -> None:
    from bpg.compiler.validator import ValidationError

    process_file = _write_v2_process(
        tmp_path,
        textwrap.dedent("""
            schema_version: 2
            process:
              name: bad_process
              trigger: start
              nodes:
                start:
                  ref:
                    package: bpg.nodes.core@v1
                    node: does_not_exist
              edges: []
        """),
    )
    catalog = discover_nodes()
    node_catalog = {key: d.manifest for key, d in catalog.items()}
    spec = parse_process_spec_v2_file(process_file)
    with pytest.raises(ValidationError, match="does_not_exist"):
        validate_process_spec_v2(spec, node_catalog=node_catalog)


# ---------------------------------------------------------------------------
# Clean virtualenv install tests
# ---------------------------------------------------------------------------

def test_bpg_nodes_core_installs_in_clean_virtualenv(tmp_path: Path) -> None:
    """bpg-nodes-core installs into a clean venv and registers entry points."""
    venv_dir = tmp_path / ".venv"
    subprocess.run(["uv", "venv", str(venv_dir)], check=True, cwd=REPO_ROOT)
    python_bin = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    subprocess.run(
        [
            "uv", "pip", "install", "--python", str(python_bin),
            "-e", str(BPG_SDK_PACKAGE),
            "-e", str(REPO_ROOT / "packages" / "bpg-nodes-core"),
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    probe = textwrap.dedent("""
        from bpg_sdk.discovery import discover_nodes
        import json
        catalog = discover_nodes()
        keys = sorted(f"{pkg}:{nid}" for pkg, nid in catalog.keys())
        print(json.dumps(keys))
    """).strip()

    result = subprocess.run(
        [str(python_bin), "-c", probe],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    discovered = json.loads(result.stdout)
    assert "bpg.nodes.core@v1:passthrough" in discovered
    assert "bpg.nodes.core@v1:flow.loop" in discovered
    assert "bpg.nodes.core@v1:math.sum_numbers" in discovered
    for key in discovered:
        assert key.startswith("bpg.nodes.core@v1:"), f"Unexpected node from other package: {key}"


def test_multiple_node_packages_discoverable_in_clean_virtualenv(tmp_path: Path) -> None:
    """Multiple first-party packages co-exist and are discovered together in a clean venv."""
    venv_dir = tmp_path / ".venv"
    subprocess.run(["uv", "venv", str(venv_dir)], check=True, cwd=REPO_ROOT)
    python_bin = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")

    subprocess.run(
        [
            "uv", "pip", "install", "--python", str(python_bin),
            "-e", str(BPG_SDK_PACKAGE),
            "-e", str(REPO_ROOT / "packages" / "bpg-nodes-core"),
            "-e", str(REPO_ROOT / "packages" / "bpg-nodes-human"),
            "-e", str(REPO_ROOT / "packages" / "bpg-nodes-search"),
        ],
        check=True,
        cwd=REPO_ROOT,
    )

    probe = textwrap.dedent("""
        from bpg_sdk.discovery import discover_nodes
        import json
        catalog = discover_nodes()
        packages = sorted(set(pkg for pkg, _ in catalog.keys()))
        print(json.dumps({"packages": packages, "total": len(catalog)}))
    """).strip()

    result = subprocess.run(
        [str(python_bin), "-c", probe],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )
    data = json.loads(result.stdout)
    assert "bpg.nodes.core@v1" in data["packages"]
    assert "bpg.nodes.human@v1" in data["packages"]
    assert "bpg.nodes.search@v1" in data["packages"]
    assert data["total"] >= 3
