from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def test_fmt_check_fails_for_non_canonical_file(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
types:
  ZType:
    z: string
  AType:
    a: string
node_types:
  z@v1:
    in: AType
    out: ZType
    provider: mock
    version: v1
    config_schema: {}
nodes:
  z:
    type: z@v1
    config: {}
trigger: z
edges: []
"""
    )
    result = runner.invoke(app, ["fmt", str(process_file), "--check"])
    assert result.exit_code == 1
    assert "Formatting needed" in result.stderr


def test_fmt_write_normalizes_and_then_check_passes(tmp_path: Path):
    process_file = tmp_path / "process.bpg.yaml"
    process_file.write_text(
        """
types:
  ZType:
    z: string
  AType:
    a: string
node_types:
  z@v1:
    in: AType
    out: ZType
    provider: mock
    version: v1
    config_schema: {}
nodes:
  z:
    type: z@v1
    config: {}
trigger: z
edges: []
"""
    )
    write_result = runner.invoke(app, ["fmt", str(process_file)])
    assert write_result.exit_code == 0
    assert "Formatted" in write_result.stdout

    check_result = runner.invoke(app, ["fmt", str(process_file), "--check"])
    assert check_result.exit_code == 0
    assert "Already canonical" in check_result.stdout

    text = process_file.read_text()
    assert text.index("AType:") < text.index("ZType:")
