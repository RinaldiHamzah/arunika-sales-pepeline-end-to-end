import csv
from decimal import Decimal

from scripts.merge_order_promotions import merge


def _write(path, fields, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_legacy_order_discount_is_allocated_once_per_unique_item_and_archived(tmp_path):
    _write(tmp_path / "promo_master.csv", ["promo_code"], [{"promo_code": "NEW15"}])
    fields = ["order_id", "order_line_id", "order_date", "qty", "unit_price", "discount_amount", "promo_code"]
    rows = [
        {"order_id": "SHP-1", "order_line_id": "1", "order_date": "2026-06-01", "qty": "1",
         "unit_price": "30.00", "discount_amount": "0.00", "promo_code": "NEW15"},
        {"order_id": "SHP-1", "order_line_id": "2", "order_date": "2026-06-01", "qty": "1",
         "unit_price": "70.00", "discount_amount": "0.00", "promo_code": "NEW15"},
    ]
    for filename, channel_fields in (
        ("shopee.csv", fields),
        ("tokopedia.csv", ["transaction_id", "item_sequence", "transaction_date", "quantity", "price", "discount_amount", "promo_code"]),
        ("website.csv", ["invoice_no", "line_item_no", "created_at", "quantity", "unit_price", "discount_amount", "promo_code"]),
        ("offline.csv", ["pos_receipt_no", "receipt_line_no", "sold_at", "units", "item_price", "discount_amount", "promo_code"]),
    ):
        _write(tmp_path / filename, channel_fields, rows if filename == "shopee.csv" else [])
    _write(tmp_path / "order_promotions.csv",
           ["source_name", "order_id", "promo_code", "discount_amount"],
           [{"source_name": "SHOPEE", "order_id": "SHP-1", "promo_code": "NEW15", "discount_amount": "10.00"}])

    preview = merge(tmp_path)
    assert len(preview) == 1
    assert (tmp_path / "order_promotions.csv").exists()

    merge(tmp_path, apply=True)
    with (tmp_path / "shopee.csv").open(newline="", encoding="utf-8") as stream:
        result = list(csv.DictReader(stream))
    assert [row["discount_amount"] for row in result] == ["3.00", "7.00"]
    assert sum((Decimal(row["discount_amount"]) for row in result), Decimal("0.00")) == Decimal("10.00")
    assert (tmp_path / "archive" / "order_promotions_legacy.csv").exists()
    assert not (tmp_path / "order_promotions.csv").exists()


def test_migration_rejects_existing_line_discount_to_prevent_double_count(tmp_path):
    _write(tmp_path / "promo_master.csv", ["promo_code"], [{"promo_code": "NEW15"}])
    channels = {
        "SHOPEE": ("shopee.csv", "order_id", "order_line_id", "qty", "unit_price"),
        "TOKOPEDIA": ("tokopedia.csv", "transaction_id", "item_sequence", "quantity", "price"),
        "WEBSITE": ("website.csv", "invoice_no", "line_item_no", "quantity", "unit_price"),
        "OFFLINE_STORE": ("offline.csv", "pos_receipt_no", "receipt_line_no", "units", "item_price"),
    }
    for source, (filename, order, line, quantity, price) in channels.items():
        fields = [order, line, "date", quantity, price, "discount_amount", "promo_code"]
        rows = [{order: "SHP-1", line: "1", "date": "2026-06-01", quantity: "1", price: "100",
                 "discount_amount": "1.00", "promo_code": "NEW15"}] if source == "SHOPEE" else []
        _write(tmp_path / filename, fields, rows)
    _write(tmp_path / "order_promotions.csv",
           ["source_name", "order_id", "promo_code", "discount_amount"],
           [{"source_name": "SHOPEE", "order_id": "SHP-1", "promo_code": "NEW15", "discount_amount": "10.00"}])

    try:
        merge(tmp_path)
    except ValueError as error:
        assert "penghitungan ganda" in str(error)
    else:
        raise AssertionError("Migrasi seharusnya menolak diskon yang sudah terisi")
