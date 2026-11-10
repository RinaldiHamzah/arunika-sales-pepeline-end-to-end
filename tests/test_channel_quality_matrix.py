"""Pastikan seluruh kontrak kanal diuji dengan kasus bisnis dan kualitas yang sama."""

import csv

import pytest

from pipeline.validation.contracts import SOURCE_NAMES
from pipeline.validation.data_quality import analyze

CHANNEL_ROWS = {
    "shopee": {
        "order_id": "SHP-QA-001",
        "order_line_id": "1",
        "order_date": "2026-02-03",
        "product_name": "Sunscreen SPF 50 PA++++ 30ml",
        "qty": "2",
        "unit_price": "100.00",
        "customer_name": "Buyer Demo",
        "customer_city": "Yogyakarta",
        "payment_method": "E-Wallet",
        "status": "completed",
        "discount_amount": "0.00",
        "promo_code": "",
    },
    "tokopedia": {
        "transaction_id": "TKP-QA-001",
        "item_sequence": "1",
        "transaction_date": "03/02/2026",
        "item_name": "Sunscreen SPF 50 PA++++ 30ml",
        "quantity": "2",
        "price": "100.00",
        "buyer_name": "Buyer Demo",
        "city": "Yogyakarta",
        "payment": "E-Wallet",
        "status": "completed",
        "discount_amount": "0.00",
        "promo_code": "",
    },
    "website": {
        "invoice_no": "WEB-QA-001",
        "line_item_no": "1",
        "created_at": "2026-02-03T10:30:00",
        "product_identifier": "SKU-001",
        "quantity": "2",
        "unit_price": "100.00",
        "total_amount": "200.00",
        "customer_email": "buyer@example.test",
        "status": "completed",
        "discount_amount": "0.00",
        "promo_code": "",
    },
    "offline": {
        "pos_receipt_no": "POS-QA-001",
        "receipt_line_no": "1",
        "sold_at": "03-Feb-2026",
        "item_description": "Sunscreen SPF 50 PA++++ 30ml",
        "units": "2",
        "item_price": "100.00",
        "store_name": "Arunika Demo",
        "store_city": "Yogyakarta",
        "payment_type": "E-Wallet",
        "status": "completed",
        "discount_amount": "0.00",
        "promo_code": "",
    },
}


def _write_csv(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def product_master(tmp_path):
    path = _write_csv(
        tmp_path / "product.csv",
        [
            {
                "sku": "SKU-001",
                "product_name": "Sunscreen SPF 50 PA++++ 30ml",
                "brand": "Arunika",
                "category": "Skincare",
                "price": "100.00",
            }
        ],
    )
    return analyze(path, "product").clean


@pytest.mark.parametrize("source", tuple(CHANNEL_ROWS))
def test_each_channel_accepts_clean_multiline_order_and_normalizes_text(tmp_path, product_master, source):
    first = dict(CHANNEL_ROWS[source])
    second = dict(first)
    spec = {
        "shopee": ("order_id", "order_line_id"),
        "tokopedia": ("transaction_id", "item_sequence"),
        "website": ("invoice_no", "line_item_no"),
        "offline": ("pos_receipt_no", "receipt_line_no"),
    }[source]
    order_column, line_column = spec
    first[order_column] = second[order_column] = f"{source.upper()}-MULTI"
    second[line_column] = "2"
    second[
        "product_name"
        if source == "shopee"
        else "item_name"
        if source == "tokopedia"
        else "product_identifier"
        if source == "website"
        else "item_description"
    ] = " sunscreen   spf 50 pa++++ 30ml " if source != "website" else "SKU-001"
    first["status"] = " COMPLETED "

    result = analyze(_write_csv(tmp_path / f"{source}.csv", [first, second]), source, product_master)

    assert len(result.clean) == 2
    assert result.summary["duplicate_records"] == 0
    assert result.summary["invalid_records"] == 0
    assert result.clean.line_number.tolist() == [1, 2]
    assert result.clean.sku.tolist() == ["SKU-001", "SKU-001"]


@pytest.mark.parametrize("source", tuple(CHANNEL_ROWS))
@pytest.mark.parametrize(
    ("field", "value", "expected_rule"),
    [
        ("quantity", "not-a-number", "INVALID_NUMBER"),
        ("status", "PENDING", "INVALID_STATUS"),
        ("product", "SKU-NOT-MAPPED", "UNMAPPED_PRODUCT"),
        ("date", "not-a-date", "INVALID_DATE"),
    ],
)
def test_each_channel_rejects_malformed_and_unmapped_values(
    tmp_path, product_master, source, field, value, expected_rule
):
    row = dict(CHANNEL_ROWS[source])
    actual_field = {
        "quantity": {"shopee": "qty", "tokopedia": "quantity", "website": "quantity", "offline": "units"},
        "status": {name: "status" for name in CHANNEL_ROWS},
        "product": {
            "shopee": "product_name",
            "tokopedia": "item_name",
            "website": "product_identifier",
            "offline": "item_description",
        },
        "date": {
            "shopee": "order_date",
            "tokopedia": "transaction_date",
            "website": "created_at",
            "offline": "sold_at",
        },
    }[field][source]
    row[actual_field] = value
    if field == "product" and source != "website":
        row[actual_field] = value

    result = analyze(_write_csv(tmp_path / f"{source}.csv", [row]), source, product_master)

    assert result.clean.empty
    assert len(result.rejected) == 1
    assert expected_rule in set(result.issues.rule)


@pytest.mark.parametrize("source", tuple(CHANNEL_ROWS))
def test_each_channel_distinguishes_exact_duplicate_from_conflicting_business_key(tmp_path, product_master, source):
    row = dict(CHANNEL_ROWS[source])
    exact = analyze(_write_csv(tmp_path / f"{source}.csv", [row, dict(row)]), source, product_master)
    assert len(exact.clean) == 1
    assert len(exact.duplicates) == 1
    assert exact.rejected.empty

    conflict = dict(row)
    quantity_field = {"shopee": "qty", "tokopedia": "quantity", "website": "quantity", "offline": "units"}[source]
    conflict[quantity_field] = "3"
    if source == "website":
        conflict["total_amount"] = "300.00"
    conflicting = analyze(_write_csv(tmp_path / f"{source}.csv", [row, conflict]), source, product_master)
    assert conflicting.clean.empty
    assert len(conflicting.rejected) == 2
    assert conflicting.issues.rule.eq("CONFLICTING_DUPLICATE").sum() == 2


def test_channel_names_used_by_quality_matrix_match_pipeline_contracts():
    assert set(CHANNEL_ROWS) == set(SOURCE_NAMES)
