"""Tes grain multi-item pada generator dan validasi tanpa basis data."""

import csv
import shutil
from pathlib import Path

import pandas as pd
import pytest

from pipeline.extract.sources import extract_all
from pipeline.promotions import apply_order_promotions, extract_promotion_sources
from pipeline.returns import extract_return_events, normalize_return_record
from pipeline.transform.standardize import clean_results_to_staging, filter_incremental_results, source_record_hash
from pipeline.validation.contracts import SOURCE_NAMES, SOURCE_SPECS, order_line_key
from pipeline.validation.data_quality import analyze
from scripts.generate_sample_data import CHANNELS, generate, order_sizes


def _save(path, rows):
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def master(tmp_path):
    rows = [
        {
            "sku": f"SKU-{index}",
            "product_name": f"Produk {index}",
            "brand": "Contoh",
            "category": "Skincare",
            "price": "100.00",
        }
        for index in range(1, 11)
    ]
    return analyze(_save(tmp_path / "product.csv", rows), "product").clean


def _web(order, line, sku="SKU-1", qty=1):
    return {
        "invoice_no": order,
        "line_item_no": str(line),
        "created_at": "2026-01-01T10:30:00",
        "product_identifier": sku,
        "quantity": str(qty),
        "unit_price": "100.00",
        "total_amount": f"{qty * 100:.2f}",
        "customer_email": "buyer@example.test",
        "status": "completed",
    }


def test_sample_data_generator_is_deterministic_and_etl_consistent(tmp_path):
    source_dir = tmp_path / "input"
    first_dir, second_dir = tmp_path / "first", tmp_path / "second"
    source_dir.mkdir()
    shutil.copy2(Path(__file__).resolve().parents[1] / "data/source/product.csv", source_dir / "product.csv")

    generate(source_dir, first_dir)
    generate(source_dir, second_dir)
    shutil.copy2(source_dir / "product.csv", first_dir / "product.csv")
    shutil.copy2(source_dir / "product.csv", second_dir / "product.csv")

    product_master = analyze(first_dir / "product.csv", "product").clean
    quality = {}
    for channel in CHANNELS:
        path = first_dir / channel["filename"]
        second_path = second_dir / channel["filename"]
        assert path.read_bytes() == second_path.read_bytes()
        source_key = next(key for key, name in SOURCE_NAMES.items() if name == channel["source"])
        result = analyze(path, source_key, product_master)
        quality[source_key] = result
        data = pd.read_csv(path, dtype=str, keep_default_na=False)
        order_column, line_column = channel["order"], channel["line"]
        item_counts = data.groupby(order_column)[line_column].nunique()
        assert len(data) == 120
        assert item_counts.min() == 1 and item_counts.max() == 5
        assert set(item_counts) == {1, 2, 3, 4, 5}
        assert data.duplicated().sum() == 1
        assert data.duplicated([order_column, line_column], keep=False).sum() == 4
        assert result.summary["valid_records"] == 112
        assert result.summary["duplicate_records"] == 1
        assert result.summary["invalid_records"] == 7

    assert order_sizes(29) and order_sizes(30) and order_sizes(31)
    sources = extract_all(first_dir)
    effective_sources, _master = apply_order_promotions(sources, extract_promotion_sources(first_dir))
    assert any(
        str(code).strip()
        for source in effective_sources
        if source.source_name != "PRODUCT_MASTER"
        for code in source.frame.get("promo_code", [])
    )
    promo_master_rows = pd.read_csv(first_dir / "promo_master.csv", dtype=str).set_index("promo_code")
    redemption_rows = pd.read_csv(first_dir / "order_promotions.csv", dtype=str)
    assert not redemption_rows.empty
    assert all(promo_master_rows.loc[code, "status"] == "active" for code in redemption_rows["promo_code"])
    assert len(redemption_rows) >= 8
    for source in effective_sources:
        if source.source_name in SOURCE_NAMES.values():
            amounts = pd.to_numeric(source.frame["discount_amount"], errors="coerce").fillna(0)
            assert amounts.gt(0).any()

    returns = extract_return_events(first_dir)
    assert len(returns.frame) == 100
    return_records = [normalize_return_record(row) for row in returns.frame.to_dict("records")]
    completed_lines = {
        SOURCE_NAMES[key]: {
            (row["order_id"], int(row["line_number"]))
            for row in result.clean.to_dict("records")
            if row["status"] == "COMPLETED"
        }
        for key, result in quality.items()
    }
    assert return_records
    assert all(
        (row["source_order_id"], row["source_line_number"]) in completed_lines[row["source_name"]]
        for row in return_records
    )


def test_contracts_have_native_line_identifier_for_each_source():
    assert {source: spec["line_number"] for source, spec in SOURCE_SPECS.items()} == {
        "shopee": "order_line_id",
        "tokopedia": "item_sequence",
        "website": "line_item_no",
        "offline": "receipt_line_no",
    }
    assert order_line_key(SOURCE_NAMES["offline"], "POS-001", 2) == ("OFFLINE_STORE", "POS-001", 2)


def test_multiline_matrix_and_same_sku_are_not_duplicates(tmp_path, master):
    item_counts = (1, 2, 3, 4, 5)
    rows = []
    for order, count in enumerate(item_counts, 1):
        rows.extend(_web(f"ORD-{order}", line, f"SKU-{line}") for line in range(1, count + 1))
    rows.extend([_web("SAME-SKU", 1, qty=1), _web("SAME-SKU", 2, qty=2)])
    result = analyze(_save(tmp_path / "website.csv", rows), "website", master)
    assert result.summary["valid_records"] == sum(item_counts) + 2
    assert result.summary["duplicate_records"] == result.summary["invalid_records"] == 0
    stage = clean_results_to_staging({"website": result})
    assert len(stage) == len(rows)
    assert not stage.duplicated(["source_name", "source_order_id", "source_line_number"]).any()


@pytest.mark.parametrize("line", ["", "0", "-1", "1.5", "abc", "2147483648"])
def test_invalid_line_number_is_rejected(tmp_path, master, line):
    result = analyze(_save(tmp_path / "website.csv", [_web("A", line)]), "website", master)
    assert result.clean.empty
    assert "INVALID_LINE_NUMBER" in set(result.issues.rule)


def test_exact_and_conflicting_duplicates_are_distinct(tmp_path, master):
    exact = _web("A", 2)
    result = analyze(_save(tmp_path / "website.csv", [exact, exact]), "website", master)
    assert (len(result.clean), len(result.duplicates), len(result.rejected)) == (1, 1, 0)
    conflict = analyze(_save(tmp_path / "website.csv", [exact, _web("A", 2, qty=5)]), "website", master)
    assert (len(conflict.clean), len(conflict.duplicates), len(conflict.rejected)) == (0, 0, 2)
    assert conflict.rejected["source_line_number"].tolist() == [2, 2]


def test_incremental_line_change_and_add_line(tmp_path, master):
    initial = analyze(_save(tmp_path / "website.csv", [_web("A", line) for line in range(1, 6)]), "website", master)
    old = {
        order_line_key("WEBSITE", row["order_id"], row["line_number"]): source_record_hash(row)
        for row in initial.clean.to_dict("records")
    }
    assert filter_incremental_results({"website": initial}, old)["website"].clean.empty
    changed_rows = [_web("A", line, qty=4 if line == 3 else 1) for line in range(1, 6)]
    changed = analyze(_save(tmp_path / "website.csv", changed_rows), "website", master)
    delta = filter_incremental_results({"website": changed}, old)["website"].clean
    assert delta["line_number"].tolist() == [3]
    expanded = analyze(_save(tmp_path / "website.csv", changed_rows + [_web("A", 6)]), "website", master)
    current = {
        order_line_key("WEBSITE", row["order_id"], row["line_number"]): source_record_hash(row)
        for row in changed.clean.to_dict("records")
    }
    delta = filter_incremental_results({"website": expanded}, current)["website"].clean
    assert delta["line_number"].tolist() == [6]
