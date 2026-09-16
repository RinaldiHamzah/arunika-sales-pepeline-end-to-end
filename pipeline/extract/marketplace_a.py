"""Shopee extractor (Marketplace A)."""
from pathlib import Path
from pipeline.extract.base import ExtractedSource, extract_delimited


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("SHOPEE", "raw.shopee_orders", path, {
        "order_id": "order_id", "order_date": "order_date", "product_name": "product_name",
        "qty": "qty", "unit_price": "unit_price",
        "customer_name": "customer_name", "customer_city": "customer_city",
        "payment_method": "payment_method", "status": "status",
    })
