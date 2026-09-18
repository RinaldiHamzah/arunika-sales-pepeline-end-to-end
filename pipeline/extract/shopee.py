"""Shopee extractor (Marketplace A)."""
from pathlib import Path
from pipeline.extract.base import ExtractedSource, extract_delimited
from pipeline.validation.contracts import raw_column_mapping


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("SHOPEE", "raw.shopee_orders", path, raw_column_mapping("shopee"))
