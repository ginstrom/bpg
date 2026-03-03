from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest


PROCESS_YAML = """
metadata:
  name: smoke-install
  version: 1.0.0

types:
  RawText:
    text: string
  ParsedNumbers:
    numbers: list<number>
  SumResult:
    sum: number
    count: number

node_types:
  intake_text@v1:
    in: RawText
    out: RawText
    provider: core.passthrough
    version: v1
    config_schema: {}
  parse_text@v1:
    in: RawText
    out: ParsedNumbers
    provider: text.parse_numbers
    version: v1
    config_schema: {}
  sum_numbers@v1:
    in: ParsedNumbers
    out: SumResult
    provider: math.sum_numbers
    version: v1
    config_schema: {}

nodes:
  intake:
    type: intake_text@v1
    config: {}
  parse:
    type: parse_text@v1
    config: {}
  sum:
    type: sum_numbers@v1
    config: {}

trigger: intake
edges:
  - from: intake
    to: parse
    with:
      text: intake.out.text
  - from: parse
    to: sum
    with:
      numbers: parse.out.numbers
output: sum.out.sum
""".strip()

INPUT_YAML = 'text: "1, 2 and 3"\n'


def _docker_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return result.returncode == 0


def test_e2e_install_in_fresh_container_smoke(tmp_path: Path) -> None:
    if not _docker_ready():
        pytest.skip("Docker is not available for container install smoke test")

    repo_root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)

    (workspace / "process.bpg.yaml").write_text(PROCESS_YAML)
    (workspace / "input.yaml").write_text(INPUT_YAML)

    image = os.environ.get("BPG_E2E_DOCKER_IMAGE", "python:3.12-slim")
    cmd = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{repo_root}:/src:ro",
        "-v",
        f"{workspace}:/work",
        "-w",
        "/work",
        image,
        "bash",
        "-lc",
        (
            "set -euo pipefail; "
            "python -m venv .venv; "
            ". .venv/bin/activate; "
            "python -m pip install --quiet --upgrade pip; "
            "python -m pip install --quiet /src; "
            "bpg plan process.bpg.yaml --state-dir .bpg-state; "
            "bpg apply process.bpg.yaml --state-dir .bpg-state --auto-approve; "
            "bpg run smoke-install --input input.yaml --state-dir .bpg-state"
        ),
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600, check=False)
    if result.returncode != 0:
        pytest.fail(
            "Container install smoke test failed\n"
            f"exit={result.returncode}\n"
            f"stdout:\n{result.stdout}\n"
            f"stderr:\n{result.stderr}"
        )

    assert "Plan for process: smoke-install" in result.stdout
    assert "Applied successfully" in result.stdout
    assert "status=completed" in result.stdout
