"""Website CSV extractor."""

from pathlib import Path

from pipeline.extract.base import ExtractedSource, extract_delimited
from pipeline.validation.contracts import raw_column_mapping


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("WEBSITE", "raw.website_transactions", path, raw_column_mapping("website"))
