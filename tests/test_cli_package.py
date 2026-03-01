from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def _write_process(tmp_path: Path, content: str) -> Path:
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(content)
    return process_file


def test_package_generates_expected_artifacts(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: package-proc
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
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["package", str(process_file), "--output-dir", str(out)])
    assert result.exit_code == 0
    assert (out / "docker-compose.yml").exists()
    assert (out / ".env.example").exists()
    assert (out / ".env").exists()
    assert (out / "process.bpg.yaml").exists()
    assert (out / "README.md").exists()
    assert (out / "package-metadata.json").exists()
    assert (out / "Dockerfile").exists()
    assert (out / "pyproject.toml").exists()
    assert (out / "uv.lock").exists()
    assert (out / "src" / "bpg" / "cli.py").exists()


def test_package_warns_on_unresolved_required_vars(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: package-proc
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
    config_schema:
      api_key: string
nodes:
  n1:
    type: n@v1
    config:
      api_key: ${API_KEY}
trigger: n1
edges: []
""",
    )
    out = tmp_path / "pkg"
    result = runner.invoke(app, ["package", str(process_file), "--output-dir", str(out)])
    assert result.exit_code == 0
    assert "unresolved required vars" in result.stdout.lower()
    assert "API_KEY=__REQUIRED__" in (out / ".env").read_text()


def test_package_with_dashboard_includes_dashboard_service(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: package-proc
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
    out = tmp_path / "pkg"
    result = runner.invoke(
        app,
        [
            "package",
            str(process_file),
            "--output-dir",
            str(out),
            "--dashboard",
            "--dashboard-port",
            "9090",
        ],
    )
    assert result.exit_code == 0
    compose_text = (out / "docker-compose.yml").read_text()
    assert "dashboard:" in compose_text
    assert "9090:9090" in compose_text


def test_package_with_image_override_sets_runtime_image(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: package-proc
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
    out = tmp_path / "pkg"
    result = runner.invoke(
        app,
        [
            "package",
            str(process_file),
            "--output-dir",
            str(out),
            "--image",
            "ghcr.io/acme/bpg:1.2.3",
        ],
    )
    assert result.exit_code == 0
    compose_text = (out / "docker-compose.yml").read_text()
    assert "ghcr.io/acme/bpg:1.2.3" in compose_text
    assert "build:" not in compose_text


def test_package_uses_default_process_file_when_argument_omitted(tmp_path: Path, monkeypatch):
    _write_process(
        tmp_path,
        """
metadata:
  name: package-proc
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
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["package"])
    assert result.exit_code == 0
    assert (tmp_path / ".bpg" / "package" / "package-proc" / "docker-compose.yml").exists()
