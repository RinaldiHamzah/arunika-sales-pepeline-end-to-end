"""Tes grain multi-item pada generator dan validasi tanpa basis data."""

import csv
from collections import Counter

import pytest

from pipeline.transform.standardize import clean_results_to_staging, filter_incremental_results, source_record_hash
from pipeline.validation.contracts import SOURCE_NAMES, SOURCE_SPECS, order_line_key
from pipeline.validation.data_quality import analyze
from scripts.generate_sample_data import FIXED_ITEM_COUNTS, records


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


def test_generator_is_deterministic_and_has_required_order_sizes():
    first = records(1)
    assert first == records(1)
    counts = Counter(row["id"] for row in first[: sum(FIXED_ITEM_COUNTS)])
    assert list(counts.values()) == list(FIXED_ITEM_COUNTS)
    for order_id, size in counts.items():
        assert [row["line_number"] for row in first if row["id"] == order_id] == list(range(1, size + 1))
    assert len({row["id"] for row in first}) < len(first)


def test_contracts_have_native_line_identifier_for_each_source():
    assert {source: spec["line_number"] for source, spec in SOURCE_SPECS.items()} == {
        "shopee": "order_line_id",
        "tokopedia": "item_sequence",
        "website": "line_item_no",
        "offline": "receipt_line_no",
    }
    assert order_line_key(SOURCE_NAMES["offline"], "POS-001", 2) == ("OFFLINE_STORE", "POS-001", 2)


def test_multiline_matrix_and_same_sku_are_not_duplicates(tmp_path, master):
    rows = []
    for order, count in enumerate(FIXED_ITEM_COUNTS, 1):
        rows.extend(_web(f"ORD-{order}", line, f"SKU-{line}") for line in range(1, count + 1))
    rows.extend([_web("SAME-SKU", 1, qty=1), _web("SAME-SKU", 2, qty=2)])
    result = analyze(_save(tmp_path / "website.csv", rows), "website", master)
    assert result.summary["valid_records"] == sum(FIXED_ITEM_COUNTS) + 2
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
