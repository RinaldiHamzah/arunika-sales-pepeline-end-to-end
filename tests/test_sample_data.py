from pathlib import Path

from pipeline.extract.sources import extract_all


ROOT = Path(__file__).resolve().parents[1]


def test_source_data_has_expected_canonical_files():
    source = ROOT / "data" / "source"
    expected = {"shopee.csv", "tokopedia.csv", "website.csv", "offline.csv", "product.csv"}
    assert all((source / filename).exists() for filename in expected)
    assert all(len(item.frame) > 0 for item in extract_all(source))
