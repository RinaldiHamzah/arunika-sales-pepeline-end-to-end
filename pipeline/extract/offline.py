"""Offline POS-store extractor."""
from pathlib import Path
from pipeline.extract.base import ExtractedSource, extract_delimited
from pipeline.validation.contracts import raw_column_mapping


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("OFFLINE_STORE", "raw.offline_store_sales", path, raw_column_mapping("offline"))
