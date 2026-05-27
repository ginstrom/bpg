from __future__ import annotations

from importlib.metadata import EntryPoint
from pathlib import Path
import json
import subprocess
import sys
import textwrap
import types

import pytest

from bpg.compiler.parser import parse_process_spec_v2_file
from bpg.compiler.spec_v2 import compile_process_spec_v2, validate_process_spec_v2
from bpg.compiler.validator import ValidationError
from bpg_sdk import Node, node
from bpg_sdk.discovery import DiscoveredNode, DiscoveryError, discover_nodes
from bpg_sdk.langgraph import build_langgraph_registration
from bpg_sdk.manifest import Idempotency, NodeManifest, ObservabilitySupport, RetrySafety, SideEffects
from bpg_sdk.temporal import build_temporal_activity_registry


REPO_ROOT = Path(__file__).resolve().parents[1]
BPG_SDK_PACKAGE = REPO_ROOT / "packages" / "bpg-sdk"


@node(
    package="bpg.nodes.tests.echo@v1",
    node_id="echo",
    input_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    output_schema={"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    capabilities=["echo"],
    side_effects=SideEffects.NONE,
    idempotency=Idempotency.IDEMPOTENT,
    retry_safety=RetrySafety.SAFE,
    observability=ObservabilitySupport.SUPPORTED,
)
def _echo(payload: dict[str, object]) -> dict[str, object]:
    return {"text": payload["text"]}


class _UppercaseNode(Node):
    manifest = NodeManifest(
        package="bpg.nodes.tests.text@v1",
        node_id="uppercase",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        capabilities=["transform"],
        side_effects=SideEffects.NONE,
        idempotency=Idempotency.IDEMPOTENT,
        retry_safety=RetrySafety.SAFE,
        observability=ObservabilitySupport.SUPPORTED,
    )

    def run(self, payload: dict[str, object]) -> dict[str, object]:
        return {"text": str(payload["text"]).upper()}


def _write_v2_process(tmp_path: Path, *, package: str, node_id: str) -> Path:
    process_file = tmp_path / "process.v2.bpg.yaml"
    process_file.write_text(
        textwrap.dedent(
            f"""
            schema_version: 2
            process:
              name: sdk_flow
              trigger: start
              nodes:
                start:
                  ref:
                    package: {package}
                    node: {node_id}
              edges: []
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    return process_file


def test_function_node_decorator_generates_manifest() -> None:
    assert _echo.manifest.package == "bpg.nodes.tests.echo@v1"
    assert _echo.manifest.node_id == "echo"
    assert _echo.manifest.capabilities == ["echo"]
    assert _echo.run({"text": "hi"}) == {"text": "hi"}


def test_class_node_exposes_declared_manifest() -> None:
    node_impl = _UppercaseNode()
    assert node_impl.manifest.package == "bpg.nodes.tests.text@v1"
    assert node_impl.manifest.node_id == "uppercase"
    assert node_impl.run({"text": "hello"}) == {"text": "HELLO"}


def test_discover_nodes_loads_sdk_entry_points(monkeypatch: pytest.MonkeyPatch) -> None:
    module_name = "tests_fake_node_sdk_plugin"
    module = types.ModuleType(module_name)
    module.echo = _echo
    module.UppercaseNode = _UppercaseNode
    sys.modules[module_name] = module

    fake_entry_points = [
        EntryPoint(name="echo", value=f"{module_name}:echo", group="bpg.nodes"),
        EntryPoint(name="uppercase", value=f"{module_name}:UppercaseNode", group="bpg.nodes"),
    ]

    monkeypatch.setattr("bpg_sdk.discovery.entry_points", lambda group=None: fake_entry_points)

    catalog = discover_nodes()

    assert sorted(catalog.keys()) == [
        ("bpg.nodes.tests.echo@v1", "echo"),
        ("bpg.nodes.tests.text@v1", "uppercase"),
    ]


def test_discover_nodes_rejects_mismatched_entry_point_name(monkeypatch: pytest.MonkeyPatch) -> None:
    module_name = "tests_fake_node_sdk_bad_plugin"
    module = types.ModuleType(module_name)
    module.echo = _echo
    sys.modules[module_name] = module

    fake_entry_points = [
        EntryPoint(name="wrong-name", value=f"{module_name}:echo", group="bpg.nodes"),
    ]
    monkeypatch.setattr("bpg_sdk.discovery.entry_points", lambda group=None: fake_entry_points)

    with pytest.raises(DiscoveryError, match="wrong-name"):
        discover_nodes()


def test_discover_nodes_wraps_load_failure_as_discovery_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _BrokenEntryPoint:
        name = "echo"
        value = "broken_pkg:echo"
        group = "bpg.nodes"

        def load(self):
            raise ImportError("no module named broken_pkg")

    monkeypatch.setattr("bpg_sdk.discovery.entry_points", lambda group=None: [_BrokenEntryPoint()])

    with pytest.raises(DiscoveryError, match="broken_pkg:echo"):
        discover_nodes()


def test_discover_nodes_wraps_instantiation_failure_as_discovery_error(monkeypatch: pytest.MonkeyPatch) -> None:
    class _RequiresArgs(Node):
        manifest = NodeManifest(
            package="bpg.nodes.tests.argnode@v1",
            node_id="argnode",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
        )

        def __init__(self, required_arg: str) -> None:
            self._arg = required_arg

        def run(self, payload: dict[str, object]) -> dict[str, object]:
            return payload

    module_name = "tests_fake_node_sdk_argnode"
    module = types.ModuleType(module_name)
    module.RequiresArgs = _RequiresArgs
    sys.modules[module_name] = module

    fake_entry_points = [
        EntryPoint(name="argnode", value=f"{module_name}:RequiresArgs", group="bpg.nodes"),
    ]
    monkeypatch.setattr("bpg_sdk.discovery.entry_points", lambda group=None: fake_entry_points)

    with pytest.raises(DiscoveryError, match="RequiresArgs"):
        discover_nodes()


def test_compiler_accepts_discovered_catalog_for_v2_process(tmp_path: Path) -> None:
    process_file = _write_v2_process(
        tmp_path,
        package="bpg.nodes.tests.echo@v1",
        node_id="echo",
    )
    spec = parse_process_spec_v2_file(process_file)
    catalog = {(_echo.manifest.package, _echo.manifest.node_id): _echo.manifest}

    validate_process_spec_v2(spec, node_catalog=catalog)
    compiled = compile_process_spec_v2(spec, node_catalog=catalog)

    assert compiled.execution_plan.nodes[0].package_id == "bpg.nodes.tests.echo@v1"
    assert compiled.execution_plan.nodes[0].package_node_id == "echo"


def test_compiler_rejects_unknown_discovered_node_for_v2_process(tmp_path: Path) -> None:
    process_file = _write_v2_process(
        tmp_path,
        package="bpg.nodes.tests.missing@v1",
        node_id="missing",
    )
    spec = parse_process_spec_v2_file(process_file)
    catalog = {(_echo.manifest.package, _echo.manifest.node_id): _echo.manifest}

    with pytest.raises(ValidationError, match="missing"):
        validate_process_spec_v2(spec, node_catalog=catalog)


def test_build_temporal_activity_registry_from_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    catalog = {
        (_echo.manifest.package, _echo.manifest.node_id): DiscoveredNode(
            manifest=_echo.manifest, implementation=_echo
        ),
        (_UppercaseNode.manifest.package, _UppercaseNode.manifest.node_id): DiscoveredNode(
            manifest=_UppercaseNode.manifest, implementation=_UppercaseNode()
        ),
    }
    registry = build_temporal_activity_registry(catalog)
    assert set(registry.keys()) == {
        "bpg.nodes.tests.echo@v1:echo",
        "bpg.nodes.tests.text@v1:uppercase",
    }
    assert registry["bpg.nodes.tests.echo@v1:echo"].manifest.node_id == "echo"


def test_build_temporal_activity_registry_from_iterable() -> None:
    nodes = [
        DiscoveredNode(manifest=_echo.manifest, implementation=_echo),
    ]
    registry = build_temporal_activity_registry(nodes)
    assert list(registry.keys()) == ["bpg.nodes.tests.echo@v1:echo"]


def test_build_langgraph_registration_defaults() -> None:
    result = build_langgraph_registration()
    assert result == {
        "engine": "langgraph",
        "tool_registry": [],
        "structured_output_schema": None,
    }


def test_build_langgraph_registration_with_tools_and_schema() -> None:
    schema = {"type": "object", "properties": {"answer": {"type": "string"}}}
    result = build_langgraph_registration(
        tool_registry=["search", "calculator"],
        structured_output_schema=schema,
    )
    assert result["tool_registry"] == ["search", "calculator"]
    assert result["structured_output_schema"] == schema
    assert result["engine"] == "langgraph"


def test_entry_point_resolution_in_clean_uv_virtualenv(tmp_path: Path) -> None:
    package_dir = tmp_path / "demo_node_pkg"
    package_dir.mkdir()
    (package_dir / "src" / "demo_node_pkg").mkdir(parents=True)
    (package_dir / "src" / "demo_node_pkg" / "__init__.py").write_text(
        textwrap.dedent(
            """
            from bpg_sdk import node
            from bpg_sdk.manifest import Idempotency, ObservabilitySupport, RetrySafety, SideEffects

            @node(
                package="bpg.nodes.demo.echo@v1",
                node_id="echo",
                input_schema={"type": "object"},
                output_schema={"type": "object"},
                capabilities=["echo"],
                side_effects=SideEffects.NONE,
                idempotency=Idempotency.IDEMPOTENT,
                retry_safety=RetrySafety.SAFE,
                observability=ObservabilitySupport.SUPPORTED,
            )
            def echo(payload):
                return payload
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )
    (package_dir / "pyproject.toml").write_text(
        textwrap.dedent(
            """
            [project]
            name = "demo-node-pkg"
            version = "0.1.0"
            requires-python = ">=3.12"
            dependencies = ["bpg-sdk"]

            [project.entry-points."bpg.nodes"]
            echo = "demo_node_pkg:echo"

            [build-system]
            requires = ["uv_build>=0.9.17,<0.10.0"]
            build-backend = "uv_build"
            """
        ).strip()
        + "\n",
        encoding="utf-8",
    )

    venv_dir = tmp_path / ".venv"
    subprocess.run(["uv", "venv", str(venv_dir)], check=True, cwd=REPO_ROOT)
    python_bin = venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python_bin), "-e", str(BPG_SDK_PACKAGE), "-e", str(package_dir)],
        check=True,
        cwd=REPO_ROOT,
    )

    probe = textwrap.dedent(
        """
        from bpg_sdk.discovery import discover_nodes
        import json

        catalog = discover_nodes()
        print(json.dumps(sorted(catalog)))
        """
    ).strip()
    result = subprocess.run(
        [str(python_bin), "-c", probe],
        check=True,
        capture_output=True,
        text=True,
        cwd=REPO_ROOT,
    )

    assert json.loads(result.stdout) == [["bpg.nodes.demo.echo@v1", "echo"]]
