from pathlib import Path

from pipeline.extract.sources import extract_all


def test_extract_all_reads_every_canonical_source():
    source_dir = Path(__file__).resolve().parents[1] / "data" / "source"
    extracted = extract_all(source_dir)
    assert [source.source_name for source in extracted] == [
        "SHOPEE",
        "TOKOPEDIA",
        "WEBSITE",
        "OFFLINE_STORE",
        "PRODUCT_MASTER",
    ]
    assert [source.source_format for source in extracted] == ["CSV", "CSV", "CSV", "CSV", "CSV"]
    assert all(len(source.frame) > 0 for source in extracted)
    assert all(len(source.checksum_sha256) == 64 for source in extracted)
    assert all(set(source.column_mapping).issubset(source.frame.columns) for source in extracted)
