"""Pindahkan diskon tingkat order ke baris item CSV kanal secara proporsional."""

from __future__ import annotations

import argparse
import csv
import shutil
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHANNELS = {
    "SHOPEE": ("shopee.csv", "order_id", "order_line_id", "qty", "unit_price"),
    "TOKOPEDIA": ("tokopedia.csv", "transaction_id", "item_sequence", "quantity", "price"),
    "WEBSITE": ("website.csv", "invoice_no", "line_item_no", "quantity", "unit_price"),
    "OFFLINE_STORE": ("offline.csv", "pos_receipt_no", "receipt_line_no", "units", "item_price"),
}


def _read(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames:
            raise ValueError(f"Header CSV kosong: {path.name}")
        return list(reader.fieldnames), list(reader)


def _allocate(discount: Decimal, gross_values: list[Decimal]) -> list[Decimal]:
    total = sum(gross_values, Decimal("0.00"))
    if total <= 0 or discount > total:
        raise ValueError("Diskon order harus positif dan tidak boleh melebihi gross order.")
    result, remaining = [], discount
    for index, gross in enumerate(gross_values):
        amount = (
            remaining
            if index == len(gross_values) - 1
            else (discount * gross / total).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        )
        amount = min(amount, gross, remaining)
        result.append(amount)
        remaining -= amount
    if remaining != 0:
        raise ValueError("Alokasi diskon tidak dapat diseimbangkan ke nilai sumber.")
    return result


def merge(source_dir: Path, *, apply: bool = False) -> list[str]:
    legacy_path = source_dir / "order_promotions.csv"
    if not legacy_path.exists():
        raise ValueError("order_promotions.csv tidak ditemukan; tidak ada migrasi yang perlu dilakukan.")
    legacy_fields, legacy_rows = _read(legacy_path)
    expected_legacy_fields = ["source_name", "order_id", "promo_code", "discount_amount"]
    if legacy_fields != expected_legacy_fields:
        raise ValueError(f"order_promotions.csv: header harus persis {','.join(expected_legacy_fields)}")
    master_path = source_dir / "promo_master.csv"
    master_fields, master_rows = _read(master_path)
    if "promo_code" not in master_fields:
        raise ValueError("promo_master.csv harus memiliki kolom promo_code.")
    known_codes = {(row.get("promo_code") or "").strip().upper() for row in master_rows}
    channels = {}
    for source_name, (filename, *_keys) in CHANNELS.items():
        path = source_dir / filename
        fields, rows = _read(path)
        required = {"discount_amount", "promo_code", *_keys}
        if not required.issubset(fields):
            raise ValueError(f"{filename}: kolom yang dibutuhkan tidak tersedia: {', '.join(sorted(required-set(fields)))}")
        channels[source_name] = (path, fields, rows)

    groups = {}
    for row_number, promo in enumerate(legacy_rows, start=2):
        source_name = (promo.get("source_name") or "").strip().upper()
        if source_name == "OFFLINE":
            source_name = "OFFLINE_STORE"
        if source_name not in CHANNELS:
            raise ValueError(f"order_promotions.csv baris {row_number}: source_name tidak dikenal.")
        order_id = (promo.get("order_id") or "").strip()
        code = (promo.get("promo_code") or "").strip().upper()
        amount = Decimal((promo.get("discount_amount") or "").strip()).quantize(Decimal("0.01"))
        key = source_name, order_id
        if not order_id or not code or code not in known_codes or amount <= 0 or key in groups:
            raise ValueError(f"order_promotions.csv baris {row_number}: key/promo tidak valid atau ganda.")
        groups[key] = (code, amount)

    updated_by_source = {}
    for source_name, (path, fields, rows) in channels.items():
        filename, order_col, line_col, qty_col, price_col = CHANNELS[source_name]
        order_rows = {}
        for row in rows:
            order_rows.setdefault((row.get(order_col) or "").strip(), []).append(row)
        for (promo_source, order_id), (code, discount) in groups.items():
            if promo_source != source_name:
                continue
            records = order_rows.get(order_id)
            if not records:
                raise ValueError(f"Order promo tidak ditemukan di {filename}: {order_id}")

            unique = {}
            copies = {}
            for row in records:
                line_id = (row.get(line_col) or "").strip()
                signature = tuple(row.get(field, "") for field in fields)
                if not line_id:
                    raise ValueError(f"{filename}: nomor baris kosong pada {order_id}")
                if line_id in unique:
                    if unique[line_id] != signature:
                        raise ValueError(f"{filename}: baris duplikat konflik pada {order_id}/{line_id}")
                    copies[line_id].append(row)
                else:
                    unique[line_id] = signature
                    copies[line_id] = [row]

            line_ids = list(copies)
            gross_values = []
            for line_id in line_ids:
                row = copies[line_id][0]
                old_code = (row.get("promo_code") or "").strip().upper()
                old_discount = Decimal((row.get("discount_amount") or "0").strip() or "0")
                if old_code not in {"", code} or old_discount < 0:
                    raise ValueError(f"{filename}: kode promo/diskon lama konflik pada {order_id}/{line_id}")
                if old_discount > 0:
                    raise ValueError(f"{filename}: diskon sudah terisi; cegah penghitungan ganda pada {order_id}/{line_id}")
                quantity = Decimal((row.get(qty_col) or "").strip())
                price = Decimal((row.get(price_col) or "").strip())
                gross_values.append((quantity * price).quantize(Decimal("0.01")))
            allocations = _allocate(discount, gross_values)
            for line_id, amount in zip(line_ids, allocations):
                for row in copies[line_id]:
                    row["promo_code"] = code
                    row["discount_amount"] = f"{amount:.2f}"
        updated_by_source[source_name] = (path, fields, rows)

    if not apply:
        return [f"{source}/{order}: {code} total {amount:.2f}" for (source, order), (code, amount) in groups.items()]

    archive = source_dir / "archive"
    archive.mkdir(exist_ok=True)
    for source_name, (path, fields, rows) in updated_by_source.items():
        backup = archive / f"{path.stem}_before_order_promotion_merge.csv"
        if backup.exists():
            raise ValueError(f"Arsip sudah ada; tidak menimpa salinan lama: {backup.name}")
        shutil.copy2(path, backup)
        temporary = path.with_suffix(path.suffix + ".tmp")
        with temporary.open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        temporary.replace(path)
    shutil.move(str(legacy_path), str(archive / "order_promotions_legacy.csv"))
    return [f"Migrasi {len(groups)} order promo ke empat CSV kanal; arsip tersedia di {archive}."]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data" / "source")
    parser.add_argument("--apply", action="store_true", help="Terapkan perubahan dan arsipkan file lama.")
    args = parser.parse_args()
    for message in merge(args.source_dir, apply=args.apply):
        print(message)
    if not args.apply:
        print("Pratinjau saja; gunakan --apply untuk memperbarui CSV dan menyimpan arsip sebelum perubahan.")


if __name__ == "__main__":
    main()
