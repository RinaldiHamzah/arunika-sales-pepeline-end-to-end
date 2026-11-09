"""Ekstraksi dan validasi CSV kejadian retur/refund."""

from __future__ import annotations

import hashlib
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

import pandas as pd

from pipeline.extract.base import ExtractedSource, extract_delimited
from pipeline.validation.rules import clean_text

RETURN_COLUMNS = (
    "source_name",
    "return_id",
    "return_line_number",
    "order_id",
    "order_line_number",
    "return_date",
    "return_reason",
    "return_status",
    "quantity_returned",
    "refund_amount",
    "refund_status",
)
CHANNEL_NAMES = {
    "SHOPEE": "SHOPEE",
    "TOKOPEDIA": "TOKOPEDIA",
    "WEBSITE": "WEBSITE",
    "OFFLINE": "OFFLINE_STORE",
    "OFFLINE_STORE": "OFFLINE_STORE",
}
RETURN_STATUSES = {"PENDING", "APPROVED", "REJECTED", "PROCESSED"}
REFUND_STATUSES = {"NOT_APPLICABLE", "PENDING", "PROCESSED", "FAILED"}


def extract_return_events(source_dir: Path, snapshot=None) -> ExtractedSource:
    """Baca returns.csv; file boleh belum tersedia untuk proyek lama."""
    path = Path(source_dir) / "returns.csv"
    mapping = {column: column for column in RETURN_COLUMNS}
    if not path.exists():
        return ExtractedSource(
            "RETURN_EVENTS",
            "raw.return_events",
            path,
            "CSV",
            pd.DataFrame(columns=RETURN_COLUMNS, dtype="string"),
            mapping,
            captured_checksum=hashlib.sha256(b"").hexdigest(),
            source_records=0,
        )
    source = extract_delimited("RETURN_EVENTS", "raw.return_events", path, mapping, snapshot)
    if tuple(source.frame.columns) != RETURN_COLUMNS:
        raise ValueError(f"returns.csv: header harus persis {','.join(RETURN_COLUMNS)}")
    return source


def _positive_integer(value, field: str) -> int:
    text = clean_text(value)
    if text is None or not text.isdecimal() or int(text) <= 0 or int(text) > 2147483647:
        raise ValueError(f"{field} harus bilangan bulat positif")
    return int(text)


def normalize_return_record(row: dict) -> dict:
    """Validasi dan normalisasi satu baris tanpa mengubah payload Raw."""
    source_name = CHANNEL_NAMES.get((clean_text(row.get("source_name")) or "").upper())
    if source_name is None:
        raise ValueError("source_name harus SHOPEE, TOKOPEDIA, WEBSITE, atau OFFLINE_STORE")

    return_id = clean_text(row.get("return_id"))
    order_id = clean_text(row.get("order_id"))
    reason = clean_text(row.get("return_reason"))
    if not return_id or not order_id or not reason:
        raise ValueError("return_id, order_id, dan return_reason wajib diisi")

    return_date_text = clean_text(row.get("return_date"))
    try:
        return_date = date.fromisoformat(return_date_text or "")
    except ValueError as exc:
        raise ValueError("return_date harus berformat YYYY-MM-DD") from exc

    return_status = (clean_text(row.get("return_status")) or "").upper()
    refund_status = (clean_text(row.get("refund_status")) or "").upper()
    if return_status not in RETURN_STATUSES:
        raise ValueError(f"return_status harus salah satu dari {', '.join(sorted(RETURN_STATUSES))}")
    if refund_status not in REFUND_STATUSES:
        raise ValueError(f"refund_status harus salah satu dari {', '.join(sorted(REFUND_STATUSES))}")

    refund_text = clean_text(row.get("refund_amount"))
    refund_amount = None
    if refund_status == "PROCESSED":
        if refund_text is None:
            raise ValueError("refund_amount wajib diisi jika refund_status PROCESSED")
        try:
            refund_amount = Decimal(refund_text)
        except InvalidOperation as exc:
            raise ValueError("refund_amount harus berupa angka desimal") from exc
        if not refund_amount.is_finite() or refund_amount < 0:
            raise ValueError("refund_amount tidak boleh negatif")
        if refund_amount > Decimal("99999999999999.99"):
            raise ValueError("refund_amount melebihi batas NUMERIC(16,2)")
        try:
            rounded_amount = refund_amount.quantize(Decimal("0.01"))
        except InvalidOperation as exc:
            raise ValueError("refund_amount melebihi presisi NUMERIC(16,2)") from exc
        if refund_amount != rounded_amount:
            raise ValueError("refund_amount maksimal dua angka desimal")
        refund_amount = rounded_amount
    elif refund_text is not None:
        raise ValueError("refund_amount hanya diisi setelah refund_status PROCESSED")

    if return_status in {"PENDING", "REJECTED"} and refund_status == "PROCESSED":
        raise ValueError("Refund tidak dapat berstatus PROCESSED untuk retur PENDING atau REJECTED")

    return {
        "source_name": source_name,
        "return_id": return_id,
        "return_line_number": _positive_integer(row.get("return_line_number"), "return_line_number"),
        "source_order_id": order_id,
        "source_line_number": _positive_integer(row.get("order_line_number"), "order_line_number"),
        "return_date": return_date,
        "return_reason": reason,
        "return_status": return_status,
        "quantity_returned": _positive_integer(row.get("quantity_returned"), "quantity_returned"),
        "refund_amount": refund_amount,
        "refund_status": refund_status,
    }
