from bpg.providers.core import DatasetSelectProvider
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
