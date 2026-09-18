"""Tests for the clean-to-warehouse transformation boundary."""

from pathlib import Path

from pipeline.transform.standardize import SOURCE_NAMES, clean_results_to_staging
from pipeline.validation.data_quality import run_quality


def test_clean_rows_transform_to_staging_contract():
    results = run_quality(Path("data/source"))
    rows = clean_results_to_staging(results)

    assert len(rows) == sum(
        result.summary["valid_records"]
        for source, result in results.items()
        if source != "product"
    )
    expected_sources = {
        SOURCE_NAMES[source]
        for source, result in results.items()
        if source != "product" and result.summary["valid_records"]
    }
    assert set(rows["source_name"]) == expected_sources
    assert rows["source_line_number"].eq(1).all()
    assert rows["mapped_sku"].notna().all()
    assert rows["sale_status"].isin({"COMPLETED", "CANCELLED", "RETURNED"}).all()
    assert not rows.duplicated(["source_name", "source_order_id", "source_line_number"]).any()