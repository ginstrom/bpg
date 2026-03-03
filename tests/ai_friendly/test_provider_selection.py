from __future__ import annotations

from bpg.scaffold.intent import scaffold_process


def test_provider_selection_accuracy_from_explicit_scaffold_flags():
    cases = [
        {"with_review": True, "expect_review_step": True},
        {"with_review": False, "expect_review_step": False},
    ]
    correct = 0
    for idx, case in enumerate(cases):
        process_doc, _ = scaffold_process(
            name=f"case-{idx}",
            description=None,
            with_review=case["with_review"],
        )
        has_review = "review_step@v1" in process_doc["node_types"]
        if has_review == case["expect_review_step"]:
            correct += 1

    accuracy = correct / len(cases)
    assert accuracy >= 1.0
