from __future__ import annotations

import shutil
import tempfile
from pathlib import Path


def write_package(output_dir: Path, files: dict[str, str], force: bool) -> None:
    if output_dir.exists() and any(output_dir.iterdir()) and not force:
        raise FileExistsError(f"Output directory '{output_dir}' already exists. Use --force to overwrite.")

    parent = output_dir.parent
    parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="bpg-package-", dir=str(parent)) as tmp:
        tmp_path = Path(tmp)
        for relative_path, content in files.items():
            file_path = tmp_path / relative_path
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content)

        if output_dir.exists():
            shutil.rmtree(output_dir)
        shutil.move(str(tmp_path), str(output_dir))
