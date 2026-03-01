from pathlib import Path
from types import SimpleNamespace

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def _write_process(tmp_path: Path, content: str) -> Path:
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(content)
    return process_file


def test_up_fails_when_unresolved_required_vars(tmp_path: Path):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: local-proc
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
    result = runner.invoke(app, ["up", str(process_file), "--local-dir", str(tmp_path / "run")])
    assert result.exit_code == 1
    assert "unresolved required vars" in result.stdout.lower()


def test_up_generates_local_runtime_bundle_and_invokes_compose(tmp_path: Path, monkeypatch):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: local-proc
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
    calls = []
    builds = []

    def _fake_compose(local_dir: Path, args: list[str]):
        calls.append((Path(local_dir), list(args)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def _fake_build(image: str, context_dir: Path):
        builds.append((image, Path(context_dir)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("bpg.cli.compose_command", _fake_compose)
    monkeypatch.setattr("bpg.cli.build_image_command", _fake_build)
    out_dir = tmp_path / "run"
    result = runner.invoke(app, ["up", str(process_file), "--local-dir", str(out_dir)])
    assert result.exit_code == 0
    assert (out_dir / "docker-compose.yml").exists()
    assert builds and builds[0][0] == "bpg-local:dev"
    assert calls and calls[0][1] == ["up", "-d"]


def test_up_with_dashboard_renders_dashboard_service(tmp_path: Path, monkeypatch):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: local-proc
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
    calls = []
    builds = []

    def _fake_compose(local_dir: Path, args: list[str]):
        calls.append((Path(local_dir), list(args)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def _fake_build(image: str, context_dir: Path):
        builds.append((image, Path(context_dir)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("bpg.cli.compose_command", _fake_compose)
    monkeypatch.setattr("bpg.cli.build_image_command", _fake_build)
    out_dir = tmp_path / "run"
    result = runner.invoke(
        app,
        [
            "up",
            str(process_file),
            "--local-dir",
            str(out_dir),
            "--dashboard",
            "--dashboard-port",
            "9091",
        ],
    )
    assert result.exit_code == 0
    compose_text = (out_dir / "docker-compose.yml").read_text()
    assert "dashboard:" in compose_text
    assert "9091:9091" in compose_text
    assert "http://localhost:9091" in result.stdout
    assert builds and builds[0][0] == "bpg-local:dev"
    assert calls and calls[0][1] == ["up", "-d"]


def test_run_missing_process_returns_clean_error(tmp_path: Path):
    state_dir = tmp_path / ".bpg-state"
    result = runner.invoke(
        app,
        ["run", "missing-process", "--state-dir", str(state_dir)],
    )
    assert result.exit_code == 1
    assert "UnboundLocalError" not in str(result.exception)


def test_up_warns_when_required_env_looks_like_placeholder(tmp_path: Path, monkeypatch):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: local-proc
  version: 1.0.0
types:
  In:
    title: string
  Out:
    ticket_id: string
    url: string
node_types:
  gitlab@v1:
    in: In
    out: Out
    provider: http.gitlab
    version: v1
    config_schema:
      project_id: string
nodes:
  issue:
    type: gitlab@v1
    config:
      project_id: myorg/backend
trigger: issue
edges: []
""",
    )
    calls = []
    builds = []

    def _fake_compose(local_dir: Path, args: list[str]):
        calls.append((Path(local_dir), list(args)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def _fake_build(image: str, context_dir: Path):
        builds.append((image, Path(context_dir)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("bpg.cli.compose_command", _fake_compose)
    monkeypatch.setattr("bpg.cli.build_image_command", _fake_build)
    out_dir = tmp_path / "run"
    result = runner.invoke(
        app,
        ["up", str(process_file), "--local-dir", str(out_dir)],
        env={"GITLAB_TOKEN": "dummy"},
    )
    assert result.exit_code == 0
    assert "look like placeholders" in result.stdout
    assert "GITLAB_TOKEN" in result.stdout
    assert builds and calls


def test_down_infers_single_local_runtime_directory(tmp_path: Path, monkeypatch):
    local_root = tmp_path / ".bpg" / "local" / "my-proc"
    local_root.mkdir(parents=True, exist_ok=True)
    calls = []

    def _fake_compose(local_dir: Path, args: list[str]):
        calls.append((Path(local_dir), list(args)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bpg.cli.compose_command", _fake_compose)
    result = runner.invoke(app, ["down"])
    assert result.exit_code == 0
    assert "Using inferred local runtime directory" in result.stdout
    assert calls
    resolved_call_dir = (tmp_path / calls[0][0]).resolve()
    assert resolved_call_dir == local_root.resolve()
    assert calls[0][1] == ["down"]


def test_down_missing_default_dir_returns_clean_error(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    result = runner.invoke(app, ["down"])
    assert result.exit_code == 1
    combined = result.stdout + getattr(result, "stderr", "")
    assert "No local runtime directory found" in combined
    assert "Traceback" not in combined


def test_up_uses_default_process_file_when_argument_omitted(tmp_path: Path, monkeypatch):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: inferred-proc
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
    calls = []
    builds = []

    def _fake_compose(local_dir: Path, args: list[str]):
        calls.append((Path(local_dir), list(args)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def _fake_build(image: str, context_dir: Path):
        builds.append((image, Path(context_dir)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bpg.cli.compose_command", _fake_compose)
    monkeypatch.setattr("bpg.cli.build_image_command", _fake_build)
    result = runner.invoke(app, ["up"])
    assert result.exit_code == 0
    assert process_file.exists()
    assert (tmp_path / ".bpg" / "local" / "inferred-proc" / "docker-compose.yml").exists()
    assert builds and calls


def test_down_accepts_process_file_and_uses_its_local_runtime_dir(tmp_path: Path, monkeypatch):
    process_file = _write_process(
        tmp_path,
        """
metadata:
  name: inferred-proc
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
    target_local_dir = tmp_path / ".bpg" / "local" / "inferred-proc"
    target_local_dir.mkdir(parents=True, exist_ok=True)
    calls = []

    def _fake_compose(local_dir: Path, args: list[str]):
        calls.append((Path(local_dir), list(args)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bpg.cli.compose_command", _fake_compose)
    result = runner.invoke(app, ["down", str(process_file)])
    assert result.exit_code == 0
    assert calls
    resolved_call_dir = (tmp_path / calls[0][0]).resolve()
    assert resolved_call_dir == target_local_dir.resolve()
    assert calls[0][1] == ["down"]


def test_down_uses_default_process_file_when_argument_omitted(tmp_path: Path, monkeypatch):
    _write_process(
        tmp_path,
        """
metadata:
  name: inferred-proc
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
    target_local_dir = tmp_path / ".bpg" / "local" / "inferred-proc"
    target_local_dir.mkdir(parents=True, exist_ok=True)
    calls = []

    def _fake_compose(local_dir: Path, args: list[str]):
        calls.append((Path(local_dir), list(args)))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("bpg.cli.compose_command", _fake_compose)
    result = runner.invoke(app, ["down"])
    assert result.exit_code == 0
    assert "Using inferred process file" in result.stdout
    assert calls
    resolved_call_dir = (tmp_path / calls[0][0]).resolve()
    assert resolved_call_dir == target_local_dir.resolve()
