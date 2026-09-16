"""Website CSV extractor."""
from pathlib import Path
from pipeline.extract.base import ExtractedSource, extract_delimited


def extract(path: Path) -> ExtractedSource:
    return extract_delimited("WEBSITE", "raw.website_transactions", path, {
        "invoice_no": "invoice_no", "created_at": "created_at", "product_identifier": "product_identifier",
        "quantity": "quantity", "unit_price": "unit_price", "total_amount": "total_amount",
        "customer_email": "customer_email", "status": "status",
    })
