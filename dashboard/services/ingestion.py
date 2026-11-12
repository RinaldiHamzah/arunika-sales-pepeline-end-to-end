"""Penanganan unggahan pada administrasi dashboard."""

from __future__ import annotations

import csv
import os
import tempfile
from io import StringIO
from pathlib import Path

from pipeline.promotions import ORDER_PROMOTION_COLUMNS, PROMO_MASTER_COLUMNS
from pipeline.returns import RETURN_COLUMNS
from pipeline.validation.contracts import RAW_COLUMNS, SOURCE_SPECS, required_raw_columns

SOURCE_DIR = Path(__file__).resolve().parents[2] / "data" / "source"
SOURCE_FILES = {
    "shopee": "shopee.csv",
    "tokopedia": "tokopedia.csv",
    "website": "website.csv",
    "offline": "offline.csv",
    "product": "product.csv",
    "promo_master": "promo_master.csv",
    "order_promotions": "order_promotions.csv",
    "returns": "returns.csv",
}
SOURCE_COLUMNS = {
    **RAW_COLUMNS,
    "promo_master": PROMO_MASTER_COLUMNS,
    "order_promotions": ORDER_PROMOTION_COLUMNS,
    "returns": RETURN_COLUMNS,
}


def _append_rows(target: Path, rows: list[dict], columns: list[str]) -> None:
    """Tambahkan batch tanpa mengganti berkas pada mount Windows; pemanggil memegang kunci pipeline."""
    output = StringIO(newline="")
    csv.DictWriter(output, fieldnames=columns).writerows(rows)
    payload = output.getvalue().encode("utf-8")
    with target.open("r+b") as file:
        original_size = file.seek(0, os.SEEK_END)
        if original_size:
            file.seek(-1, os.SEEK_END)
            if file.read(1) not in (b"\n", b"\r"):
                payload = b"\n" + payload
        file.seek(0, os.SEEK_END)
        try:
            file.write(payload)
            file.flush()
            os.fsync(file.fileno())
        except Exception:
            # Batalkan tambahan yang belum berhasil; isi lama tidak ditulis ulang.
            file.truncate(original_size)
            file.flush()
            os.fsync(file.fileno())
            raise


def append_csv_batch(source_key: str, payload: bytes, mode: str = "append") -> int:
    """Validasi kontrak CSV sumber lalu tambahkan isinya ke berkas sumber terkait."""
    if source_key not in SOURCE_FILES:
        raise ValueError("Source tidak didukung.")
    if mode not in {"append", "correct"}:
        raise ValueError("Mode upload harus append atau correct.")
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV harus menggunakan encoding UTF-8.") from error

    reader = csv.DictReader(StringIO(decoded))
    expected = list(SOURCE_COLUMNS[source_key])
    required = list(required_raw_columns(source_key)) if source_key in RAW_COLUMNS else expected
    allowed_headers = (required, expected) if source_key in RAW_COLUMNS else (expected,)
    if reader.fieldnames not in allowed_headers:
        raise ValueError(
            f"Header {source_key}.csv harus berupa kontrak lama ({', '.join(required)}) "
            f"atau kontrak lengkap ({', '.join(expected)})."
        )
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError("Jumlah kolom pada satu atau lebih baris CSV tidak sesuai dengan header.")
    if not rows:
        raise ValueError("CSV tidak memiliki baris transaksi.")

    target = SOURCE_DIR / SOURCE_FILES[source_key]
    if not target.exists():
        raise ValueError(f"Source target tidak ditemukan: {target.name}")
    with target.open("r", newline="", encoding="utf-8-sig") as file:
        existing = csv.DictReader(file)
        if existing.fieldnames not in allowed_headers:
            raise ValueError(f"Header berkas sumber {target.name} tidak sesuai kontrak yang didukung.")
        existing_rows = list(existing)
    if any(None in row or any(value is None for value in row.values()) for row in existing_rows):
        raise ValueError(f"Berkas sumber {target.name} memiliki baris dengan jumlah kolom tidak sesuai.")

    for row in [*existing_rows, *rows]:
        for column in expected:
            row.setdefault(column, "")

    if mode == "correct":
        # Koreksi eksplisit, bukan aturan ambigu 'baris terakhir menang'.
        if source_key in SOURCE_SPECS:
            spec = SOURCE_SPECS[source_key]
            keys = (spec["order_id"], spec["line_number"])
        else:
            keys = {
                "product": ("sku",), "promo_master": ("promo_code",),
                "order_promotions": ("source_name", "order_id"),
                "returns": ("source_name", "return_id", "return_line_number"),
            }[source_key]

        def key(row, *, strict=True):
            values = []
            for column in keys:
                value = str(row[column]).strip()
                if column in {"source_name", "promo_code"}:
                    value = value.upper()
                if column == "source_name" and value == "OFFLINE":
                    value = "OFFLINE_STORE"
                if column in {"order_line_id", "item_sequence", "line_item_no", "receipt_line_no", "return_line_number"}:
                    if value.isdecimal() and int(value) > 0:
                        value = str(int(value))
                    elif strict:
                        raise ValueError("Nomor baris business key koreksi harus bilangan bulat positif.")
                if not value and strict:
                    raise ValueError("Business key koreksi tidak boleh kosong.")
                values.append(value)
            return tuple(values)

        updates = {}
        for row in rows:
            identity = key(row)
            if identity in updates and updates[identity] != row:
                raise ValueError("Batch koreksi memiliki business key sama dengan isi berbeda.")
            updates[identity] = row
        known = {key(row, strict=False) for row in existing_rows}
        if updates.keys() - known:
            raise ValueError("Key koreksi belum ada di sumber. Gunakan Tambah batch untuk data baru.")
        existing_rows = [row for row in existing_rows if key(row, strict=False) not in updates]
        rows = list(updates.values())

    if existing.fieldnames == expected and mode == "append":
        _append_rows(target, rows, expected)
        return len(rows)

    # Peningkatan kontrak lama tetap memerlukan penggantian berkas utuh.
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", newline="", encoding="utf-8", dir=target.parent, suffix=".tmp", delete=False
        ) as file:
            temporary_path = Path(file.name)
            writer = csv.DictWriter(file, fieldnames=expected)
            writer.writeheader()
            writer.writerows(existing_rows)
            writer.writerows(rows)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
    return len(rows)
