"""Build the complete list of project source extracts."""

from pathlib import Path

from pipeline.extract import offline, product, shopee, tokopedia, website


def extract_all(source_dir: Path):
    return [
        shopee.extract(source_dir / "shopee.csv"),
        tokopedia.extract(source_dir / "tokopedia.csv"),
        website.extract(source_dir / "website.csv"),
        offline.extract(source_dir / "offline.csv"),
        product.extract(source_dir / "product.csv"),
    ]
