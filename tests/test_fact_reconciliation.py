from pathlib import Path

import pandas as pd

from pipeline.extract.base import ExtractedSource
from pipeline.load.fact_loader import _snapshot_business_keys


def _source(frame, *, source_records=None):
    return ExtractedSource(
        source_name="WEBSITE",
        raw_table="raw.website_transactions",
        file_path=Path("website.csv"),
        source_format="CSV",
        frame=frame,
        column_mapping={"invoice_no": "invoice_no", "line_item_no": "line_item_no"},
        source_records=source_records,
    )


def test_snapshot_keys_use_source_order_and_line_identity():
    source = _source(
        pd.DataFrame(
            [
                {"invoice_no": " WEB-1 ", "line_item_no": "1", "quantity": "bad"},
                {"invoice_no": "WEB-1", "line_item_no": "2", "quantity": "2"},
            ]
        ),
        source_records=2,
    )

    keys, reason = _snapshot_business_keys(source)

    assert reason is None
    assert keys == {("WEB-1", 1), ("WEB-1", 2)}


def test_snapshot_reconciliation_is_skipped_when_identity_is_unavailable():
    source = _source(
        pd.DataFrame([{"invoice_no": "WEB-1", "line_item_no": "", "quantity": "1"}]),
        source_records=1,
    )

    keys, reason = _snapshot_business_keys(source)

    assert keys is None
    assert "business key" in reason


def test_snapshot_reconciliation_is_skipped_when_scan_is_partial():
    source = _source(
        pd.DataFrame(columns=["invoice_no", "line_item_no"]),
        source_records=25,
    )

    keys, reason = _snapshot_business_keys(source)

    assert keys is None
    assert reason == "snapshot sumber tidak lengkap"
