from pathlib import Path

from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def test_visualize_import_registry_file_shows_actionable_error(tmp_path: Path) -> None:
    registry_file = tmp_path / "search-resources.bpg.yaml"
    registry_file.write_text(
        """
types:
  SearchStoreKey:
    value: enum(search_main)
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["visualize", str(registry_file)])

    assert result.exit_code == 1
    assert "shared import/registry file" in result.stderr
    assert "nodes/edges/trigger" in result.stderr
