"""Product master CSV extractor."""

from pathlib import Path

from pipeline.extract.base import ExtractedSource, extract_delimited
from pipeline.validation.contracts import raw_column_mapping


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("PRODUCT_MASTER", "raw.product_master", path, raw_column_mapping("product"))
