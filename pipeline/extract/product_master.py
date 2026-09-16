"""Product master CSV extractor."""
from pathlib import Path
from pipeline.extract.base import ExtractedSource, extract_delimited


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("PRODUCT_MASTER", "raw.product_master", path, {
        "sku": "sku", "product_name": "product_name", "brand": "brand", "category": "category", "price": "price",
    })
