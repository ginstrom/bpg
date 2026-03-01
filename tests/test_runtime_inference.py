from pathlib import Path

from bpg.compiler.parser import parse_process_file
from bpg.packaging.inference import build_runtime_spec


def _write_process(tmp_path: Path, content: str) -> Path:
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(content)
    return process_file


def test_build_runtime_spec_for_package_defaults_postgres(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p1
  version: 1.0.0
types:
  T:
    ok: bool
node_types:
  n@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  n1:
    type: n@v1
    config: {}
trigger: n1
edges: []
""",
    )
    process = parse_process_file(process_file)
    spec = build_runtime_spec(process, process_file.read_text(), mode="package", env={})
    assert spec.ledger_backend == "postgres"
    assert "postgres" in spec.services
    assert spec.runtime_image == "bpg-package:local"


def test_build_runtime_spec_for_local_defaults_sqlite_file(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p1
  version: 1.0.0
types:
  T:
    ok: bool
node_types:
  n@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  n1:
    type: n@v1
    config: {}
trigger: n1
edges: []
""",
    )
    process = parse_process_file(process_file)
    spec = build_runtime_spec(process, process_file.read_text(), mode="local", env={})
    assert spec.ledger_backend == "sqlite-file"
    assert "postgres" not in spec.services
    assert spec.runtime_image == "bpg-local:dev"


def test_build_runtime_spec_with_dashboard_enabled(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: p1
  version: 1.0.0
types:
  T:
    ok: bool
node_types:
  n@v1:
    in: object
    out: object
    provider: mock
    version: v1
    config_schema: {}
nodes:
  n1:
    type: n@v1
    config: {}
trigger: n1
edges: []
""",
    )
    process = parse_process_file(process_file)
    spec = build_runtime_spec(
        process,
        process_file.read_text(),
        mode="local",
        env={},
        dashboard=True,
        dashboard_port=9090,
    )
    assert spec.dashboard_enabled is True
    assert spec.dashboard_port == 9090
    assert "dashboard" in spec.services
    assert spec.runtime_image == "bpg-local:dev"
    env_by_name = {item.name: item for item in spec.env_vars}
    assert env_by_name["DASHBOARD_PORT"].value == "9090"
