from pathlib import Path

import pytest

from bpg.providers.core import CsvReadProvider, DatasetSelectProvider
from bpg.providers.base import ExecutionContext


def test_dataset_select_provider_selects_rows_in_input_order():
    provider = DatasetSelectProvider()
    handle = provider.invoke(
        input={"row_ids": [3, 1]},
        config={
            "rows": [
                {"row_id": 1, "review": "one"},
                {"row_id": 2, "review": "two"},
                {"row_id": 3, "review": "three"},
            ]
        },
        context=ExecutionContext(
            run_id="r1",
            node_name="select",
            idempotency_key="k1",
            process_name="p1",
        ),
    )
    out = provider.await_result(handle)
    assert out["rows"] == [
        {"row_id": 3, "review": "three"},
        {"row_id": 1, "review": "one"},
    ]


def test_csv_read_provider_reads_rows_maps_fields_and_selects(tmp_path: Path):
    csv_path = tmp_path / "reviews.csv"
    csv_path.write_text(
        "review,sentiment\n"
        "alpha,positive\n"
        "beta,negative\n"
        "gamma,neutral\n",
        encoding="utf-8",
    )

    provider = CsvReadProvider()
    handle = provider.invoke(
        input={"row_ids": [3, 1]},
        config={
            "path": str(csv_path),
            "row_id_field": "row_id",
            "review_column": "review",
            "sentiment_column": "sentiment",
            "output_review_field": "review",
            "output_sentiment_field": "source_sentiment",
        },
        context=ExecutionContext(
            run_id="r1",
            node_name="read_csv",
            idempotency_key="k1",
            process_name="p1",
        ),
    )
    out = provider.await_result(handle)
    assert out["rows"] == [
        {"row_id": 3, "review": "gamma", "source_sentiment": "neutral"},
        {"row_id": 1, "review": "alpha", "source_sentiment": "positive"},
    ]


def test_csv_read_provider_requires_path():
    provider = CsvReadProvider()
    with pytest.raises(ValueError, match="requires config.path"):
        provider.invoke(
            input={"row_ids": [1]},
            config={},
            context=ExecutionContext(
                run_id="r1",
                node_name="read_csv",
                idempotency_key="k1",
                process_name="p1",
            ),
        )
