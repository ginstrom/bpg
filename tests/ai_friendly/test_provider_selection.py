from __future__ import annotations

from pathlib import Path

import yaml

from bpg.scaffold.intent import scaffold_from_intent


def test_provider_selection_accuracy_from_intent_corpus():
    corpus_path = Path(__file__).parent / "corpus" / "provider_selection.yaml"
    corpus = yaml.safe_load(corpus_path.read_text())
    correct = 0
    total = 0
    for case in corpus["cases"]:
        total += 1
        process_doc, _ = scaffold_from_intent(case["intent"])
        has_review = "review_step@v1" in process_doc["node_types"]
        if has_review == bool(case["expect_review_step"]):
            correct += 1

    accuracy = correct / total
    assert accuracy >= 1.0
