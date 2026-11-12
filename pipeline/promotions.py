"""Validasi katalog promo dan diskon aktual pada baris transaksi kanal."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pipeline.extract.base import ExtractedSource, extract_delimited
from pipeline.validation.contracts import SOURCE_NAMES, SOURCE_SPECS
from pipeline.validation.rules import clean_text, parse_date

PROMO_MASTER_COLUMNS = (
    "promo_code",
    "promo_name",
    "discount_type",
    "discount_value",
    "start_date",
    "end_date",
    "status",
)
def extract_promotion_sources(source_dir: Path) -> list[ExtractedSource]:
    """Baca katalog promo; kode dan diskon aktual datang dari CSV tiap kanal."""
    path = source_dir / "promo_master.csv"
    source = extract_delimited(
        "PROMO_MASTER", "raw.promo_master", path, {column: column for column in PROMO_MASTER_COLUMNS}
    )
    if tuple(source.frame.columns) != PROMO_MASTER_COLUMNS:
        raise ValueError(f"promo_master.csv: header harus persis {','.join(PROMO_MASTER_COLUMNS)}")
    return [source]


def _decimal(value, field: str, *, allow_zero: bool = False) -> Decimal:
    try:
        result = Decimal(str(value).strip())
    except Exception as exc:
        raise ValueError(f"Nilai {field} tidak valid: {value!r}") from exc
    if not result.is_finite() or result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"Nilai {field} harus {'minimal 0' if allow_zero else 'lebih dari 0'}")
    if result != result.quantize(Decimal("0.01")):
        raise ValueError(f"Nilai {field} maksimal dua angka desimal")
    return result.quantize(Decimal("0.01"))


def _read_master(source: ExtractedSource) -> dict[str, dict]:
    master = {}
    for line, row in enumerate(source.frame.to_dict("records"), start=2):
        code = (clean_text(row["promo_code"]) or "").upper()
        name = clean_text(row["promo_name"])
        kind = (clean_text(row["discount_type"]) or "").lower()
        status = (clean_text(row["status"]) or "").lower()
        value_text = clean_text(row["discount_value"])
        start, start_error = parse_date(row["start_date"], "shopee")
        end, end_error = parse_date(row["end_date"], "shopee")
        if not code or not name or kind not in {"fixed", "percentage"}:
            raise ValueError(f"promo_master.csv baris {line}: kode, nama, atau tipe diskon tidak valid")
        if status not in {"active", "expired", "paused"}:
            raise ValueError(f"promo_master.csv baris {line}: status harus active, expired, atau paused")
        if start_error or end_error or start.date() > end.date():
            raise ValueError(f"promo_master.csv baris {line}: rentang tanggal tidak valid")
        value = _decimal(value_text, "discount_value")
        if kind == "percentage" and value > 100:
            raise ValueError(f"promo_master.csv baris {line}: persentase tidak boleh melebihi 100")
        normalized = {
            **row,
            "promo_code": code,
            "promo_name": name,
            "discount_type": kind,
            "discount_value": value,
            "start_date": start.date(),
            "end_date": end.date(),
            "status": status,
        }
        if code in master and master[code] != normalized:
            raise ValueError(f"promo_master.csv baris {line}: promo_code duplikat dengan isi berbeda {code}")
        master[code] = normalized
    return master


def apply_channel_promotions(
    transaction_sources: list[ExtractedSource], promo_sources: list[ExtractedSource], *, metrics: dict | None = None
) -> tuple[list[ExtractedSource], dict[str, dict]]:
    """Validasi kode dan diskon aktual yang sudah dicatat per baris di CSV kanal."""
    if len(promo_sources) != 1 or promo_sources[0].source_name != "PROMO_MASTER":
        raise ValueError("Pipeline hanya menerima promo_master.csv; promo aktual harus ada di CSV kanal.")
    master_source = promo_sources[0]
    master = _read_master(master_source)
    if metrics is not None:
        metrics["PROMO_MASTER"] = {
            "valid": len(master), "duplicates": len(master_source.frame) - len(master)
        }
    output = []
    for source in transaction_sources:
        source_key = next((key for key, value in SOURCE_NAMES.items() if value == source.source_name), None)
        if source_key is None or source.frame.empty:
            output.append(source)
            continue
        spec = SOURCE_SPECS[source_key]
        frame = source.frame.copy()
        for column in ("discount_amount", "promo_code"):
            if column not in frame:
                frame[column] = ""
        frame["promo_code"] = frame["promo_code"].fillna("").astype("string")
        frame["discount_amount"] = frame["discount_amount"].fillna("0").astype("string")

        for index, row in frame.iterrows():
            order_id = str(row[spec["order_id"]]).strip()
            key = (source.source_name, order_id)
            code = (clean_text(row.get("promo_code")) or "").upper()
            discount_text = clean_text(row.get("discount_amount"))
            discount = _decimal(discount_text, "discount_amount", allow_zero=True) if discount_text else Decimal("0.00")
            if not code and discount > 0:
                raise ValueError(f"Diskon baris kanal memerlukan promo_code pada {key[0]}/{key[1]}")
            if code:
                if code not in master:
                    raise ValueError(f"Promo {code} pada CSV kanal tidak ditemukan di promo_master.csv")
                parsed_date, date_error = parse_date(row[spec["order_date"]], source_key)
                promo = master[code]
                if date_error or not promo["start_date"] <= parsed_date.date() <= promo["end_date"]:
                    raise ValueError(f"Promo {code} tidak berlaku pada tanggal order {key[0]}/{key[1]}")
                quantity = _decimal(row[spec["quantity"]], "quantity")
                unit_price = _decimal(row[spec["unit_price"]], "unit_price", allow_zero=True)
                gross = (quantity * unit_price).quantize(Decimal("0.01"))
                if discount > gross:
                    raise ValueError(f"Diskon baris melebihi gross pada {key[0]}/{key[1]}")
        output.append(
            ExtractedSource(
                source.source_name,
                source.raw_table,
                source.file_path,
                source.source_format,
                frame,
                source.column_mapping,
                source.row_numbers,
                source.captured_checksum,
                source.source_records,
            )
        )
    return output, master
