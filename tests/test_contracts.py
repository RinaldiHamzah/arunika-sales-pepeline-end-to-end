"""Regression tests for the canonical data contract."""

from pipeline.validation.analysis import PRODUCT_COLUMNS, SALES_COLUMNS
from pipeline.validation.contracts import (
    BUSINESS_KEY,
    CLEAN_PRODUCT_COLUMNS,
    CLEAN_SALES_COLUMNS,
    RAW_COLUMNS,
    SOURCE_SPECS,
    VALID_STATUSES,
)
from pipeline.validation.data_quality import (
    META,
)
from pipeline.validation.data_quality import (
    PRODUCT_COLUMNS as RAW_PRODUCT_COLUMNS,
)
from pipeline.validation.data_quality import (
    SALES_COLUMNS as INTERNAL_SALES_COLUMNS,
)


def test_contract_definitions_are_shared_by_pipeline_interfaces():
    assert PRODUCT_COLUMNS == list(CLEAN_PRODUCT_COLUMNS)
    assert SALES_COLUMNS == list(CLEAN_SALES_COLUMNS)
    assert RAW_PRODUCT_COLUMNS == list(RAW_COLUMNS["product"])
    assert META == ["source", "source_file", "source_row_number", "source_sha256"]
    assert INTERNAL_SALES_COLUMNS[0:4] == ["source", "order_id", "line_number", "order_date"]
    assert INTERNAL_SALES_COLUMNS[-4:] == ["status", "source_file", "source_row_number", "source_sha256"]


def test_raw_source_contract_and_business_rules_are_explicit():
    assert set(SOURCE_SPECS) == {"shopee", "tokopedia", "website", "offline"}
    assert all(tuple(spec.values()) == RAW_COLUMNS[source] for source, spec in SOURCE_SPECS.items())
    assert BUSINESS_KEY == ("source", "order_id", "line_number")
    assert VALID_STATUSES == {"COMPLETED", "CANCELLED", "RETURNED"}
    assert "customer_id" not in CLEAN_SALES_COLUMNS
