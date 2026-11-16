from pathlib import Path

import pandas as pd
import pytest

from pipeline.extract.base import ExtractedSource, filter_unseen_rows, raw_payload_hash
from pipeline.promotions import _read_master, apply_channel_promotions, extract_promotion_sources
from pipeline.validation.contracts import SOURCE_SPECS


def _source(name, path, records):
    frame = pd.DataFrame(records, dtype="string")
    return ExtractedSource(
        name.upper(), f"raw.{name}", Path(path), "CSV", frame,
        {column: column for column in frame.columns}, source_records=len(frame),
    )


def _master_file(tmp_path):
    (tmp_path / "promo_master.csv").write_text(
        "promo_code,promo_name,discount_type,discount_value,start_date,end_date,status\n"
        "NEW15,Promo Pengguna Baru,percentage,15,2026-01-01,2026-12-31,active\n",
        encoding="utf-8",
    )
    return extract_promotion_sources(tmp_path)


def _shopee_row(order="ORDER-1", line="1", *, qty="1", price="100", discount="0", code=""):
    spec = SOURCE_SPECS["shopee"]
    columns = list(spec.values()) + ["discount_amount", "promo_code"]
    return dict(zip(columns, [order, line, "2026-06-01", "Serum", qty, price, "A", "Jakarta", "COD",
                              "completed", discount, code]))


def test_promo_master_deduplicates_identical_rows_and_rejects_conflicts(tmp_path):
    sources = _master_file(tmp_path)
    master = sources[0]
    master.frame.loc[len(master.frame)] = master.frame.iloc[0]
    assert len(_read_master(master)) == 1
    master.frame.loc[1, "discount_value"] = "16"
    with pytest.raises(ValueError, match="duplikat dengan isi berbeda"):
        _read_master(master)


def test_promo_raw_delta_keeps_only_new_or_changed_catalog_rows(tmp_path):
    source = _master_file(tmp_path)[0]
    original_rows = []
    for index in range(10):
        row = source.frame.iloc[0].to_dict()
        row["promo_code"] = f"OLD{index:02d}"
        original_rows.append(row)
    known_hashes = {raw_payload_hash(row) for row in original_rows}

    added_rows = []
    for index in range(12):
        row = source.frame.iloc[0].to_dict()
        row["promo_code"] = f"NEW{index:02d}"
        added_rows.append(row)
    expanded = ExtractedSource(
        source.source_name,
        source.raw_table,
        source.file_path,
        source.source_format,
        pd.DataFrame(original_rows + added_rows, dtype="string"),
        source.column_mapping,
        tuple(range(1, 23)),
        source.captured_checksum,
        source_records=22,
    )

    delta = filter_unseen_rows(expanded, known_hashes)

    assert len(delta.frame) == 12
    assert delta.row_numbers == tuple(range(11, 23))


def test_each_channel_row_carries_its_own_allocated_discount(tmp_path):
    promos = _master_file(tmp_path)
    shopee = _source("shopee", tmp_path / "shopee.csv", [
        _shopee_row(line="1", price="30", discount="3.00", code="new15"),
        _shopee_row(line="2", price="70", discount="7.00", code="NEW15"),
    ])
    tokopedia = _source("tokopedia", tmp_path / "tokopedia.csv", [{
        "transaction_id": "ORDER-1", "item_sequence": "1", "transaction_date": "01/06/2026",
        "item_name": "Powder", "quantity": "1", "price": "100", "buyer_name": "B",
        "city": "Jakarta", "payment": "COD", "status": "completed",
        "discount_amount": "0", "promo_code": "",
    }])

    metrics = {}
    enriched, master = apply_channel_promotions([shopee, tokopedia], promos, metrics=metrics)

    assert master["NEW15"]["discount_type"] == "percentage"
    assert enriched[0].frame["discount_amount"].tolist() == ["3.00", "7.00"]
    assert enriched[0].frame["promo_code"].tolist() == ["new15", "NEW15"]
    assert enriched[1].frame["discount_amount"].tolist() == ["0"]
    assert metrics["PROMO_MASTER"]["promo_codes_checked"] == 2
    assert metrics["PROMO_MASTER"]["promo_codes_matched"] == 2


def test_channel_promo_code_must_map_to_master_and_be_in_date_range(tmp_path):
    promos = _master_file(tmp_path)
    with pytest.raises(ValueError, match="tidak ditemukan di promo_master"):
        apply_channel_promotions([_source("shopee", "shopee.csv", [_shopee_row(code="UNKNOWN")])], promos)
    invalid_date = _shopee_row(code="NEW15")
    invalid_date["order_date"] = "2027-01-01"
    with pytest.raises(ValueError, match="tidak berlaku"):
        apply_channel_promotions([_source("shopee", "shopee.csv", [invalid_date])], promos)


def test_discount_requires_promo_code_and_cannot_exceed_item_gross(tmp_path):
    promos = _master_file(tmp_path)
    no_code = _shopee_row(discount="1.00")
    with pytest.raises(ValueError, match="memerlukan promo_code"):
        apply_channel_promotions([_source("shopee", "shopee.csv", [no_code])], promos)
    too_large = _shopee_row(discount="101.00", code="NEW15")
    with pytest.raises(ValueError, match="melebihi gross"):
        apply_channel_promotions([_source("shopee", "shopee.csv", [too_large])], promos)


@pytest.mark.parametrize("status", ["paused", "expired"])
def test_promo_must_be_active_even_when_order_is_inside_promo_date_range(tmp_path, status):
    promos = _master_file(tmp_path)
    promos[0].frame.loc[0, "status"] = status

    with pytest.raises(ValueError, match=f"berstatus {status}"):
        apply_channel_promotions(
            [_source("shopee", "shopee.csv", [_shopee_row(discount="15", code="NEW15")])],
            promos,
        )


def test_extract_only_requires_promo_master(tmp_path):
    promos = _master_file(tmp_path)
    assert len(promos) == 1
    assert promos[0].source_name == "PROMO_MASTER"


def test_retired_order_promotion_table_is_absent_from_bootstrap_schema():
    root = Path(__file__).resolve().parents[1]
    raw_schema = (root / "database/schema/3_raw_tables.sql").read_text(encoding="utf-8").lower()
    audit_schema = (root / "database/schema/7_audit_tables.sql").read_text(encoding="utf-8").lower()

    assert "raw.order_promotions" not in raw_schema
    assert "raw.order_promotions" not in audit_schema


def test_email_report_does_not_treat_channel_promo_as_separate_source(tmp_path):
    from pipeline.alerts import format_pipeline_report

    body = format_pipeline_report({
        "status": "SUCCESS",
        "report_summary": {
            "raw": {},
            "auxiliary_sources": [{"source_name": "PROMO_MASTER", "source_records": 1, "validated": 1}],
        },
    })
    assert "- Master Promo:" in body
    assert "ORDER PROMOTION" not in body
