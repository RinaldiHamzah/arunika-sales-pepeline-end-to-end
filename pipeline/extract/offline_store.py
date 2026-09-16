"""Offline POS-store extractor."""
from pathlib import Path
from pipeline.extract.base import ExtractedSource, extract_delimited


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("OFFLINE_STORE", "raw.offline_store_sales", path, {
        "pos_receipt_no": "pos_receipt_no", "sold_at": "sold_at", "item_description": "item_description",
        "units": "units", "item_price": "item_price", "store_name": "store_name",
        "store_city": "store_city", "payment_type": "payment_type", "status": "status",
    })
