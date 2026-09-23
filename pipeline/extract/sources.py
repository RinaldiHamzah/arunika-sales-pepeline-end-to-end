"""Build the complete list of project source extracts."""

from pathlib import Path

from pipeline.extract import offline, product, shopee, tokopedia, website
from pipeline.extract.base import extract_delimited
from pipeline.validation.contracts import raw_column_mapping


def extract_all(source_dir: Path, snapshots=None):
    if snapshots is not None:
        definitions = [
            ("shopee", "SHOPEE", "raw.shopee_orders"),
            ("tokopedia", "TOKOPEDIA", "raw.tokopedia_transactions"),
            ("website", "WEBSITE", "raw.website_transactions"),
            ("offline", "OFFLINE_STORE", "raw.offline_store_sales"),
            ("product", "PRODUCT_MASTER", "raw.product_master"),
        ]
        return [
            extract_delimited(name, table, source_dir / f"{key}.csv", raw_column_mapping(key), snapshots.get(name))
            for key, name, table in definitions
        ]
    return [
        shopee.extract(source_dir / "shopee.csv"),
        tokopedia.extract(source_dir / "tokopedia.csv"),
        website.extract(source_dir / "website.csv"),
        offline.extract(source_dir / "offline.csv"),
        product.extract(source_dir / "product.csv"),
    ]
