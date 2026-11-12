"""Validasi master promo dan terapkan penukaran promo tingkat order."""

from __future__ import annotations

import hashlib
from decimal import ROUND_HALF_UP, Decimal
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
ORDER_PROMOTION_COLUMNS = ("source_name", "order_id", "promo_code", "discount_amount")
CHANNEL_CODES = {**{name: name for name in SOURCE_NAMES.values()}, "OFFLINE": "OFFLINE_STORE"}


def extract_promotion_sources(source_dir: Path) -> list[ExtractedSource]:
    """Baca dua CSV promo; keduanya tetap dibedakan dari file transaksi kanal."""
    definitions = (
        ("PROMO_MASTER", "raw.promo_master", "promo_master.csv", PROMO_MASTER_COLUMNS),
        ("ORDER_PROMOTIONS", "raw.order_promotions", "order_promotions.csv", ORDER_PROMOTION_COLUMNS),
    )
    sources = []
    for name, table, filename, columns in definitions:
        path = source_dir / filename
        source = extract_delimited(name, table, path, {column: column for column in columns})
        if tuple(source.frame.columns) != columns:
            raise ValueError(f"{filename}: header harus persis {','.join(columns)}")
        sources.append(source)
    return sources


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


def _allocate(discount: Decimal, gross_values: list[Decimal]) -> list[Decimal]:
    total = sum(gross_values, Decimal("0.00"))
    if discount > total:
        raise ValueError("Diskon order melebihi nilai kotor order")
    allocations = []
    remaining = discount
    for index, gross in enumerate(gross_values):
        if index == len(gross_values) - 1:
            amount = remaining
        else:
            amount = (discount * gross / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            amount = min(amount, gross, remaining)
        allocations.append(amount)
        remaining -= amount
    return allocations


def apply_order_promotions(
    transaction_sources: list[ExtractedSource], promo_sources: list[ExtractedSource], *, metrics: dict | None = None
) -> tuple[list[ExtractedSource], dict[str, dict]]:
    """Validasi penggunaan promo dan alokasikan diskon order ke grain baris produk."""
    master_source, order_source = promo_sources
    master = _read_master(master_source)
    redemptions = {}
    for line, row in enumerate(order_source.frame.to_dict("records"), start=2):
        source_name = (clean_text(row["source_name"]) or "").upper()
        source_name = CHANNEL_CODES.get(source_name)
        order_id = clean_text(row["order_id"])
        code = (clean_text(row["promo_code"]) or "").upper()
        if source_name is None or not order_id or not code:
            raise ValueError(f"order_promotions.csv baris {line}: kanal, order_id, atau promo_code tidak valid")
        if code not in master:
            raise ValueError(f"order_promotions.csv baris {line}: promo_code {code} tidak ada di promo_master.csv")
        key = (source_name, order_id)
        amount = _decimal(row["discount_amount"], "discount_amount")
        if key in redemptions:
            previous = redemptions[key]
            if previous["promo_code"] == code and previous["discount_amount"] == amount:
                continue
            raise ValueError(f"order_promotions.csv baris {line}: promo ganda dengan isi berbeda untuk {source_name}/{order_id}; gunakan koreksi data")
        redemptions[key] = {"promo_code": code, "discount_amount": amount, "line_number": line}

    if metrics is not None:
        metrics.update({
            "PROMO_MASTER": {"valid": len(master), "duplicates": len(master_source.frame) - len(master)},
            "ORDER_PROMOTIONS": {"valid": len(redemptions), "duplicates": len(order_source.frame) - len(redemptions)},
        })
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

        groups = {}
        for index, row in frame.iterrows():
            key = (source.source_name, str(row[spec["order_id"]]).strip())
            groups.setdefault(key, []).append(index)
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
        for key, redemption in redemptions.items():
            if key[0] != source.source_name or key not in groups:
                continue
            indices = groups[key]
            # Upload ulang tidak boleh menggandakan basis alokasi diskon.
            # Pertahankan salinan baris agar validasi downstream tetap mencatat duplikatnya.
            unique_lines = {}
            copies = {}
            for index in indices:
                line_id = str(frame.at[index, spec["line_number"]]).strip()
                if line_id.isdecimal():
                    line_id = str(int(line_id))
                signature = tuple(str(frame.at[index, column]).strip() for column in frame.columns)
                if line_id in unique_lines:
                    first_index, first_signature = unique_lines[line_id]
                    if signature != first_signature:
                        raise ValueError(f"Baris order promo memiliki konflik isi: {key[0]}/{key[1]}/{line_id}")
                    copies[first_index].append(index)
                else:
                    unique_lines[line_id] = (index, signature)
                    copies[index] = [index]
            indices = list(copies)
            source_codes = {
                (clean_text(frame.at[index, "promo_code"]) or "").upper()
                for index in indices
                if clean_text(frame.at[index, "promo_code"])
            }
            source_discounts = [
                _decimal(clean_text(frame.at[index, "discount_amount"]) or "0", "discount_amount", allow_zero=True)
                for index in indices
            ]
            if any(amount > 0 for amount in source_discounts) or source_codes - {redemption["promo_code"]}:
                raise ValueError(f"Promo tingkat order dan promo baris sumber sama-sama terisi untuk {key[0]}/{key[1]}")
            promo = master[redemption["promo_code"]]
            gross = []
            order_date = None
            for index in indices:
                row = frame.loc[index]
                quantity = _decimal(row[spec["quantity"]], "quantity")
                unit_price = _decimal(row[spec["unit_price"]], "unit_price", allow_zero=True)
                gross.append((quantity * unit_price).quantize(Decimal("0.01")))
                parsed_date, date_error = parse_date(row[spec["order_date"]], source_key)
                if date_error:
                    raise ValueError(f"Tanggal order tidak valid untuk {key[0]}/{key[1]}")
                order_date = parsed_date.date()
            if not promo["start_date"] <= order_date <= promo["end_date"]:
                raise ValueError(f"Promo {redemption['promo_code']} tidak berlaku pada tanggal order {key[0]}/{key[1]}")
            amounts = _allocate(redemption["discount_amount"], gross)
            for index, amount in zip(indices, amounts):
                for copy_index in copies[index]:
                    frame.at[copy_index, "promo_code"] = redemption["promo_code"]
                    frame.at[copy_index, "discount_amount"] = str(amount)
        # Redemption hanya dapat dicocokkan jika file kanal dipindai penuh.
        full_scan = source.source_records is None or len(source.frame) == source.source_records
        if full_scan:
            missing = [key for key in redemptions if key[0] == source.source_name and key not in groups]
            if missing:
                raise ValueError(f"Order promo tidak ditemukan di CSV kanal: {missing[0][0]}/{missing[0][1]}")
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


def snapshot_source(
    source: ExtractedSource, *, effective: bool = False, promotion_checksum: str | None = None
) -> ExtractedSource:
    """Buat salinan metadata snapshot untuk payload hasil pengayaan tanpa mengubah Raw asli."""
    name = f"{source.source_name}_EFFECTIVE" if effective else source.source_name
    checksum = source.checksum_sha256
    if effective and promotion_checksum:
        checksum = hashlib.sha256(f"{checksum}:{promotion_checksum}".encode()).hexdigest()
    return ExtractedSource(
        name,
        source.raw_table,
        source.file_path,
        source.source_format,
        source.frame,
        source.column_mapping,
        source.row_numbers,
        checksum,
        source.source_records,
    )
