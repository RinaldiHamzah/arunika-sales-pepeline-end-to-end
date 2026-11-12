"""Ekstraktor CSV master produk."""

from pathlib import Path

from pipeline.extract.base import ExtractedSource, extract_delimited
from pipeline.validation.contracts import raw_column_mapping

PRODUCT_SOURCE_FILE = "product_master.csv"
LEGACY_PRODUCT_SOURCE_FILE = "product.csv"


def source_path(source_dir: Path) -> Path:
    """Pilih nama sumber master produk baru, dengan fallback untuk proyek lama."""
    source_dir = Path(source_dir)
    current = source_dir / PRODUCT_SOURCE_FILE
    if current.exists() or not (source_dir / LEGACY_PRODUCT_SOURCE_FILE).exists():
        return current
    return source_dir / LEGACY_PRODUCT_SOURCE_FILE


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("PRODUCT_MASTER", "raw.product_master", path, raw_column_mapping("product"))
