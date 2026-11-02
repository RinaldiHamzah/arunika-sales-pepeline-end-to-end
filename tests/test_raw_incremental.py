"""Tes pemrosesan inkremental pada Raw sebelum validasi."""

from pathlib import Path

import pandas as pd

from pipeline.extract.base import ExtractedSource, filter_unseen_rows, raw_payload_hash


def test_filter_unseen_rows_keeps_only_new_rows_and_original_lineage():
    source = ExtractedSource(
        source_name="SHOPEE",
        raw_table="raw.shopee_orders",
        file_path=Path("shopee.csv"),
        source_format="CSV",
        frame=pd.DataFrame(
            [
                {"order_id": "SHP-001", "qty": "1"},
                {"order_id": "SHP-002", "qty": "2"},
                {"order_id": "SHP-003", "qty": "1"},
            ]
        ),
        column_mapping={"order_id": "order_id", "qty": "qty"},
    )

    known = {raw_payload_hash(source.frame.iloc[0].to_dict())}
    incremental = filter_unseen_rows(source, known)

    assert incremental.frame["order_id"].tolist() == ["SHP-002", "SHP-003"]
    assert incremental.row_numbers == (2, 3)


def test_filter_unseen_rows_skips_unchanged_snapshot():
    source = ExtractedSource(
        source_name="WEBSITE",
        raw_table="raw.website_transactions",
        file_path=Path("website.csv"),
        source_format="CSV",
        frame=pd.DataFrame([{"invoice_no": "WEB-001"}]),
        column_mapping={"invoice_no": "invoice_no"},
    )

    incremental = filter_unseen_rows(source, {raw_payload_hash({"invoice_no": "WEB-001"})})

    assert incremental.frame.empty
    assert incremental.row_numbers == ()


def test_changed_duplicate_rechecks_unchanged_sibling():
    original = {"invoice_no": "WEB-001", "line_item_no": "2", "quantity": "1"}
    changed = {**original, "quantity": "5"}
    source = ExtractedSource(
        source_name="WEBSITE",
        raw_table="raw.website_transactions",
        file_path=Path("website.csv"),
        source_format="CSV",
        frame=pd.DataFrame([original, changed]),
        column_mapping={key: key for key in original},
    )
    delta = filter_unseen_rows(source, {raw_payload_hash(original)})
    assert delta.row_numbers == (1, 2)
