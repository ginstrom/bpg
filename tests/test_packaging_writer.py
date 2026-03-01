from pathlib import Path

import pytest

from bpg.packaging.writer import write_package


def test_write_package_fails_when_output_exists_without_force(tmp_path: Path):
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "old.txt").write_text("old")
    with pytest.raises(FileExistsError):
        write_package(output_dir=out, files={"README.md": "x"}, force=False)


def test_write_package_overwrites_when_force_true(tmp_path: Path):
    out = tmp_path / "bundle"
    out.mkdir()
    (out / "old.txt").write_text("old")
    write_package(output_dir=out, files={"README.md": "new"}, force=True)
    assert (out / "README.md").read_text() == "new"
