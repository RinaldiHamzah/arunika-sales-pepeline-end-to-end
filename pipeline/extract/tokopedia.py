"""Tokopedia CSV extractor (Marketplace B)."""

from pathlib import Path

from pipeline.extract.base import ExtractedSource, extract_delimited
from pipeline.validation.contracts import raw_column_mapping


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("TOKOPEDIA", "raw.tokopedia_transactions", path, raw_column_mapping("tokopedia"))
