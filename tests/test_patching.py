from __future__ import annotations

import pytest

from bpg.compiler.patching import PatchApplyError, apply_json_patch


def test_apply_json_patch_add_replace_remove():
    doc = {
        "types": {"A": {"x": "string"}},
        "nodes": {"n1": {"type": "t@v1", "config": {}}},
        "edges": [],
    }
    patched = apply_json_patch(
        doc,
        [
            {"op": "add", "path": "$.types.B", "value": {"y": "bool"}},
            {"op": "replace", "path": "$.nodes.n1.type", "value": "t@v2"},
            {"op": "remove", "path": "$.types.A"},
        ],
    )
    assert "A" not in patched["types"]
    assert patched["types"]["B"]["y"] == "bool"
    assert patched["nodes"]["n1"]["type"] == "t@v2"


def test_apply_json_patch_invalid_path_raises():
    with pytest.raises(PatchApplyError, match="Unsupported patch path"):
        apply_json_patch({"types": {}}, [{"op": "add", "path": "/types/A", "value": {}}])
