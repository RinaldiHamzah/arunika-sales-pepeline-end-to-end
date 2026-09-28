"""Safe source-file upload handling for dashboard administration."""

from __future__ import annotations

import csv
from io import StringIO
from pathlib import Path

from pipeline.validation.contracts import RAW_COLUMNS

SOURCE_DIR = Path(__file__).resolve().parents[2] / "data" / "source"
SOURCE_FILES = {
    "shopee": "shopee.csv",
    "tokopedia": "tokopedia.csv",
    "website": "website.csv",
    "offline": "offline.csv",
    "product": "product.csv",
}


def append_csv_batch(source_key: str, payload: bytes) -> int:
    """Validate a source CSV contract and append it to the source batch file."""
    if source_key not in SOURCE_FILES:
        raise ValueError("Source tidak didukung.")
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV harus menggunakan encoding UTF-8.") from error

    reader = csv.DictReader(StringIO(decoded))
    expected = list(RAW_COLUMNS[source_key])
    if reader.fieldnames != expected:
        raise ValueError(f"Header {source_key}.csv harus persis: {', '.join(expected)}")
    rows = list(reader)
    if not rows:
        raise ValueError("CSV tidak memiliki baris transaksi.")

    target = SOURCE_DIR / SOURCE_FILES[source_key]
    if not target.exists():
        raise ValueError(f"Source target tidak ditemukan: {target.name}")
    with target.open("a", newline="", encoding="utf-8") as file:
        csv.DictWriter(file, fieldnames=expected).writerows(rows)
    return len(rows)
