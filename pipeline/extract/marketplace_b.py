"""Tokopedia CSV extractor (Marketplace B)."""
from pathlib import Path
from pipeline.extract.base import ExtractedSource, extract_delimited


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("TOKOPEDIA", "raw.tokopedia_transactions", path, {
        "transaction_id": "transaction_id", "transaction_date": "transaction_date", "item_name": "item_name",
        "quantity": "quantity", "price": "price",
        "buyer_name": "buyer_name", "city": "city", "payment": "payment", "status": "status",
    })
