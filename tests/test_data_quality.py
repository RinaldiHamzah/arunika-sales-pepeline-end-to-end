"""Quality contracts tested with isolated fixtures; never regenerate user sources."""

import csv
from decimal import Decimal
from hashlib import sha256

import pandas as pd
import pytest

from pipeline.validation.data_quality import ROOT, analyze, read_source, run_quality
from pipeline.validation.rules import clean_text, match_key, number, parse_date


def save(path, rows):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def master(tmp_path):
    p = save(
        tmp_path / "product.csv",
        [dict(sku="001", product_name="Brand SPF 50 PA++++ 30ml", brand="Brand", category="Skincare", price="100.10")],
    )
    return analyze(p, "product").clean


def web(order="00001", **changes):
    return dict(
        invoice_no=order,
        created_at="Apr 03, 2026",
        product_identifier="001",
        quantity="2",
        unit_price="100.10",
        total_amount="200.20",
        customer_email="buyer@example.test",
        status="completed",
        **changes,
    )


def test_normalization_preserves_product_specifics():
    assert clean_text("  LABORE\u00a0 SPF 50  ") == "LABORE SPF 50"
    assert match_key("BRAND-SPF-50") == match_key("brand spf 50")
    assert match_key("PA++++") != match_key("PA+++")
    assert match_key("Shade 01") != match_key("Shade 02")


@pytest.mark.parametrize("value", ["", "NaN", "Infinity", "zero", "-1", "0", "1.5", "2147483648"])
def test_bad_quantities(value):
    assert number(value, integer=True)[1] is not None


def test_money_exact_and_not_silently_rounded():
    assert number("100.10")[0] * 2 == Decimal("200.20")
    assert number("100.123")[1] is not None
    assert number("1,000")[1] is not None


def test_explicit_date_formats():
    assert parse_date("02/07/2026", "tokopedia")[0].isoformat() == "2026-07-02T00:00:00"
    assert parse_date("Mar 08, 2026", "website")[0] == parse_date("08-Mar-2026", "offline")[0]
    assert parse_date("31/02/2026", "shopee")[1] == "INVALID_DATE"
    assert parse_date("02/07/2026", "website")[1] == "INVALID_DATE"


def test_semantic_duplicates_and_optional_missing(tmp_path, master):
    first = web()
    first["customer_email"] = ""
    second = dict(first, product_identifier=" BRAND-SPF-50-PA++++-30ml ")
    result = analyze(save(tmp_path / "web.csv", [first, second]), "website", master)
    assert len(result.clean) == 1 and len(result.duplicates) == 1
    assert result.clean.iloc[0]["order_id"] == "00001"
    assert result.clean.iloc[0]["sku"] == "001"
    assert result.clean["customer_email"].isna().all()
    assert result.clean["quantity"].dtype == "Int64"
    assert result.clean.iloc[0]["gross_amount"] == Decimal("200.20")


def test_internal_clean_data_excludes_source_only_customer_id(tmp_path, master):
    row = {
        "order_id": "SHP-1",
        "order_date": "03/04/2026",
        "product_name": "001",
        "qty": "1",
        "unit_price": "100.10",
        "customer_id": "C001",
        "customer_name": "Buyer",
        "customer_city": "Jakarta",
        "payment_method": "COD",
        "status": "completed",
    }
    result = analyze(save(tmp_path / "shopee.csv", [row]), "shopee", master)
    assert "customer_id" not in result.clean.columns
    assert result.clean.iloc[0]["customer_name"] == "Buyer"


def test_conflicting_duplicate_quarantines_all_versions(tmp_path, master):
    rows = [web(), dict(web(), quantity="3", total_amount="300.30")]
    result = analyze(save(tmp_path / "web.csv", rows), "website", master)
    assert result.clean.empty and len(result.rejected) == 2
    assert result.rejected.reasons.str.contains("CONFLICTING_DUPLICATE").all()


def test_invalid_required_and_amount_are_not_imputed(tmp_path, master):
    rows = [
        dict(web("1"), quantity=""),
        dict(web("2"), total_amount="200.21"),
        dict(web("3"), product_identifier="Unknown Product"),
        dict(web("4"), status="pending"),
    ]
    result = analyze(save(tmp_path / "web.csv", rows), "website", master)
    assert len(result.rejected) == 4 and result.clean.empty
    assert {"MISSING_REQUIRED", "AMOUNT_MISMATCH", "UNMAPPED_PRODUCT", "INVALID_STATUS"} <= set(result.issues.rule)


def test_master_conflict_does_not_choose_arbitrary_price(tmp_path):
    row = dict(sku="001", product_name="One", brand="Brand", category="Skincare", price="10")
    result = analyze(save(tmp_path / "master.csv", [row, dict(row, price="20")]), "product")
    assert result.clean.empty and len(result.rejected) == 2


def test_schema_and_bad_csv_fail_explicitly(tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("sku,sku\n1,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="duplicate column"):
        read_source(path)
    path.write_text("sku,price\n1,1,extra\n", encoding="utf-8")
    with pytest.raises(ValueError, match="row width"):
        read_source(path)
    path.write_text("sku\n1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="missing columns"):
        analyze(path, "product")


def test_current_sources_unchanged_reconciled_and_reproducible(tmp_path):
    paths = list((ROOT / "data/source").glob("*.csv"))
    before = {p: sha256(p.read_bytes()).hexdigest() for p in paths}
    first = run_quality(output_dir=tmp_path / "first")
    second = run_quality(output_dir=tmp_path / "second")
    for name, result in first.items():
        assert result.summary == second[name].summary
        s = result.summary
        assert s["extracted_records"] == s["valid_records"] + s["duplicate_records"] + s["invalid_records"]
        pd.testing.assert_frame_equal(result.clean, second[name].clean)
        if name != "product":
            assert result.clean.sku.isin(first["product"].clean.sku).all()
    for p in (tmp_path / "first").iterdir():
        assert p.read_bytes() == (tmp_path / "second" / p.name).read_bytes()
    assert before == {p: sha256(p.read_bytes()).hexdigest() for p in paths}
