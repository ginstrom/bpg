from __future__ import annotations

import json
from pathlib import Path

import yaml
from typer.testing import CliRunner

from bpg.cli import app


runner = CliRunner()


def _doctor_ok(process_file: Path) -> bool:
    result = runner.invoke(app, ["doctor", str(process_file), "--json"])
    payload = json.loads(result.stdout)
    return bool(payload.get("ok"))


def test_common_repair_case_fixed_within_one_round(tmp_path: Path):
    corpus_path = Path(__file__).parent / "corpus" / "repair_cases.yaml"
    corpus = yaml.safe_load(corpus_path.read_text())
    for case in corpus["cases"]:
        process_file = tmp_path / f"{case['name']}.bpg.yaml"
        process_file.write_text(case["process"])

        # Round 0: should fail
        assert _doctor_ok(process_file) is False

        suggest = runner.invoke(app, ["suggest-fix", str(process_file), "--json"])
        payload = json.loads(suggest.stdout)
        assert payload["suggestions"], "Expected at least one suggested patch"

        patch_file = tmp_path / f"{case['name']}.patch.json"
        patch_file.write_text(json.dumps(payload["suggestions"][0]["patch"]))
        applied = runner.invoke(app, ["apply-patch", str(process_file), str(patch_file)])
        assert applied.exit_code == 0

        # Round 1 repair succeeds for this common case.
        assert _doctor_ok(process_file) is True
