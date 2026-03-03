from __future__ import annotations

import difflib
import json

import yaml

from bpg.compiler.normalize import normalize_process_dict
from bpg.compiler.patching import apply_json_patch
from bpg.scaffold.intent import scaffold_from_intent


def _render(doc: dict) -> str:
    return yaml.safe_dump(normalize_process_dict(doc), sort_keys=False)


def _changed_lines(before: str, after: str) -> int:
    count = 0
    for line in difflib.unified_diff(before.splitlines(), after.splitlines(), lineterm=""):
        if line.startswith("+") or line.startswith("-"):
            if line.startswith("+++") or line.startswith("---"):
                continue
            count += 1
    return count


def test_insert_review_step_keeps_diff_small():
    base_doc, _ = scaffold_from_intent("extract customer ids")
    before = _render(base_doc)

    patch = [
        {
            "op": "add",
            "path": "$.types.ReviewOut",
            "value": {"approved": "bool", "result": "string"},
        },
        {
            "op": "add",
            "path": "$.node_types.review_step@v1",
            "value": {
                "in": "TaskOutput",
                "out": "ReviewOut",
                "provider": "dashboard.form",
                "version": "v1",
                "config_schema": {},
            },
        },
        {
            "op": "add",
            "path": "$.nodes.review",
            "value": {"type": "review_step@v1", "config": {}},
        },
        {
            "op": "add",
            "path": "$.edges[1]",
            "value": {"from": "task", "to": "review", "with": {"result": "task.out.result"}},
        },
        {"op": "replace", "path": "$.output", "value": "review.out"},
    ]
    after_doc = apply_json_patch(base_doc, patch)
    after = _render(after_doc)
    changed = _changed_lines(before, after)

    # Benchmark guardrail: inserting one review step should stay reasonably local.
    assert changed <= 40, json.dumps({"changed_lines": changed})
