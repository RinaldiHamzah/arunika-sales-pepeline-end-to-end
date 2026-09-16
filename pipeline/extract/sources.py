"""Build the complete list of project source extracts."""
from pathlib import Path

from pipeline.extract import marketplace_a, marketplace_b, offline_store, product_master, website


def extract_all(source_dir: Path):
    return [
        marketplace_a.extract(source_dir / "shopee.csv"),
        marketplace_b.extract(source_dir / "tokopedia.csv"),
        website.extract(source_dir / "website.csv"),
        offline_store.extract(source_dir / "offline.csv"),
        product_master.extract(source_dir / "product.csv"),
    ]
