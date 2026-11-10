"""Buat data demo deterministik yang beragam dan konsisten untuk pipeline ETL."""

from __future__ import annotations

import argparse
import csv
import random
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "source"
SEED = 20261109
ROW_COUNT = 100

FIRST_NAMES = (
    "Alya",
    "Bima",
    "Citra",
    "Dimas",
    "Eka",
    "Farah",
    "Gilang",
    "Hana",
    "Intan",
    "Joko",
    "Kirana",
    "Laras",
    "Maya",
    "Naufal",
    "Oki",
    "Putri",
    "Raka",
    "Salsa",
    "Tegar",
    "Utami",
    "Vina",
    "Wahyu",
    "Yuni",
    "Zahra",
    "Aditya",
    "Bella",
    "Dewi",
    "Fajar",
    "Galih",
    "Hasna",
    "Ilham",
    "Kevin",
    "Luthfi",
    "Nadia",
    "Reza",
    "Sinta",
    "Tania",
    "Yusuf",
    "Ari",
)
LAST_NAMES = (
    "Putri",
    "Pratama",
    "Lestari",
    "Saputra",
    "Wulandari",
    "Maheswari",
    "Ramadhan",
    "Permata",
    "Kusuma",
    "Hidayat",
    "Ananda",
    "Puspita",
    "Firmansyah",
    "Utomo",
    "Sari",
    "Wijaya",
    "Nugraha",
    "Amalia",
    "Setiawan",
    "Anggraini",
    "Santoso",
    "Maharani",
    "Kurniawan",
    "Safitri",
)
CITIES = (
    "Jakarta",
    "Bandung",
    "Surabaya",
    "Yogyakarta",
    "Semarang",
    "Medan",
    "Makassar",
    "Denpasar",
    "Malang",
    "Palembang",
    "Bogor",
    "Solo",
    "Balikpapan",
    "Tangerang",
    "Depok",
    "Bekasi",
)
PAYMENTS = ("Transfer Bank", "E-Wallet", "Credit Card", "COD", "Cash")
REASONS = (
    "Produk rusak saat diterima",
    "Varian tidak sesuai pesanan",
    "Produk tidak sesuai deskripsi",
    "Kemasan bocor",
    "Berubah pikiran",
    "Produk menyebabkan iritasi",
    "Pesanan ganda",
)
PROMOS = (
    ("Q1HEMAT5", "Hemat Awal Tahun", "percentage", "5", "2026-01-01", "2026-03-31", "expired"),
    ("RAMADAN15", "Promo Ramadan", "percentage", "15", "2026-02-01", "2026-04-30", "expired"),
    ("GAJIAN10", "Promo Periode Gajian", "percentage", "10", "2026-04-01", "2026-06-30", "expired"),
    ("MIDYEAR12", "Promo Tengah Tahun", "percentage", "12", "2026-07-01", "2026-08-31", "expired"),
    ("SEPTEMBER20", "Promo September", "percentage", "20", "2026-09-01", "2026-09-30", "expired"),
    ("OCTOBER8", "Promo Oktober", "percentage", "8", "2026-10-01", "2026-12-31", "active"),
    ("FIXED10K", "Potongan Nominal Sepuluh Ribu", "fixed", "10000", "2026-01-01", "2026-12-31", "active"),
    ("FIXED15K", "Potongan Nominal Lima Belas Ribu", "fixed", "15000", "2026-01-01", "2026-12-31", "paused"),
    ("NEWUSER10", "Diskon Pengguna Baru", "percentage", "10", "2026-01-01", "2026-12-31", "active"),
    ("FLASH25", "Flash Sale Juni", "percentage", "25", "2026-06-10", "2026-06-20", "expired"),
    ("VIPMEMBER20", "Promo Member VIP", "percentage", "20", "2026-01-01", "2026-12-31", "paused"),
    ("LEGACY2025", "Promo Periode Tahun Lalu", "fixed", "20000", "2025-01-01", "2025-12-31", "expired"),
)
PROMO_RULES = {
    row[0]: (row[2], Decimal(row[3]), date.fromisoformat(row[4]), date.fromisoformat(row[5]), row[6]) for row in PROMOS
}
SIZE_COUNTS = {
    29: (1, 5, 8, 10, 5),
    30: (1, 3, 14, 9, 3),
    31: (1, 6, 12, 9, 3),
}
CHANNELS = (
    {
        "filename": "shopee.csv",
        "source": "SHOPEE",
        "prefix": "SHP",
        "order": "order_id",
        "line": "order_line_id",
        "product": "product_name",
        "customer": "customer_name",
        "date_format": "%Y-%m-%d",
        "kind": "shopee",
    },
    {
        "filename": "tokopedia.csv",
        "source": "TOKOPEDIA",
        "prefix": "TKP",
        "order": "transaction_id",
        "line": "item_sequence",
        "product": "item_name",
        "customer": "buyer_name",
        "date_format": "%d/%m/%Y",
        "kind": "tokopedia",
    },
    {
        "filename": "website.csv",
        "source": "WEBSITE",
        "prefix": "WEB",
        "order": "invoice_no",
        "line": "line_item_no",
        "product": "product_identifier",
        "customer": "customer_email",
        "date_format": "%Y-%m-%dT%H:%M:%S",
        "kind": "website",
    },
    {
        "filename": "offline.csv",
        "source": "OFFLINE_STORE",
        "prefix": "POS",
        "order": "pos_receipt_no",
        "line": "receipt_line_no",
        "product": "item_description",
        "customer": None,
        "date_format": "%d-%b-%Y",
        "kind": "offline",
    },
)
OFFLINE_STORES = (
    ("Arunika Beauty Grand Indonesia", "Jakarta"),
    ("Arunika Beauty Tunjungan Plaza", "Surabaya"),
    ("Arunika Beauty Paris Van Java", "Bandung"),
    ("Arunika Beauty Malioboro", "Yogyakarta"),
    ("Arunika Beauty Paragon Mall", "Semarang"),
    ("Arunika Beauty Beachwalk", "Denpasar"),
)


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def write_csv(directory: Path, filename: str, fields: tuple[str, ...], rows: list[dict]) -> None:
    with (directory / filename).open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def product_catalog(source_dir: Path) -> list[dict]:
    products = read_csv(source_dir / "product.csv")
    if not products:
        raise ValueError("product.csv harus berisi Product Master sebelum data demo dibuat")
    return [
        {**row, "price": Decimal(row["price"]), "sku": row["sku"].strip(), "product_name": row["product_name"].strip()}
        for row in products
    ]


def customer_profiles() -> list[dict]:
    profiles = []
    for index, (first, last) in enumerate(((first, last) for first in FIRST_NAMES for last in LAST_NAMES), start=1):
        name = f"{first.strip()} {last}"
        slug = f"{first}.{last}.{index:03}".lower()
        profiles.append(
            {
                "id": f"CUS-{index:04}",
                "name": name,
                "email": f"{slug}@example.test",
                "city": CITIES[(index * 7) % len(CITIES)],
            }
        )
    return profiles


def existing_order_ids(source_dir: Path, channel: dict) -> list[str]:
    rows = read_csv(source_dir / channel["filename"])
    order_column = channel["order"]
    ids = list(dict.fromkeys(row[order_column].strip() for row in rows if row.get(order_column, "").strip()))
    if ids:
        return ids
    return [f"{channel['prefix']}-{index:04}" for index in range(1, 31)]


def order_sizes(order_count: int) -> list[int]:
    if order_count not in SIZE_COUNTS:
        raise ValueError(f"Distribusi demo mendukung 29–31 order; ditemukan {order_count}")
    sizes = [size for size, count in enumerate(SIZE_COUNTS[order_count], start=1) for _ in range(count)]
    if len(sizes) != order_count or sum(sizes) != ROW_COUNT:
        raise AssertionError("Distribusi item demo tidak berjumlah tepat 100 baris")
    return sizes


def promotion_for_order(order_date: date, order_index: int, gross: Decimal):
    if order_index % 4 != 1:
        return None
    eligible = [
        code
        for code, (_kind, _value, starts, ends, status) in PROMO_RULES.items()
        if starts <= order_date <= ends and status == "active"
    ]
    if not eligible:
        return None
    code = eligible[order_index % len(eligible)]
    kind, value, _starts, _ends, _status = PROMO_RULES[code]
    discount = (
        (gross * value / 100).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if kind == "percentage" else value
    )
    return code, min(discount, gross)


def product_description(product: dict, kind: str, rng: random.Random) -> str:
    name = product["product_name"]
    if kind == "website":
        return product["sku"]
    return rng.choice((name, name.upper(), name.replace(" ", "-"), f" {name} "))


def build_channel(source_dir: Path, channel: dict, products: list[dict], customers: list[dict], offset: int):
    rng = random.Random(SEED + offset)
    order_ids = existing_order_ids(source_dir, channel)
    sizes = order_sizes(len(order_ids))
    # Baris kasus kualitas selalu menempati satu order satu-item tersendiri.
    remaining = sizes[1:]
    rng.shuffle(remaining)
    sizes = [1, *remaining]

    rows, redemptions = [], []
    cursor = 0
    for order_index, (order_id, item_count) in enumerate(zip(order_ids, sizes)):
        customer = rng.choice(customers)
        order_date = date(2026, 1, 1) + timedelta(days=rng.randrange(304))
        status = rng.choices(("COMPLETED", "CANCELLED", "RETURNED"), weights=(76, 12, 12), k=1)[0]
        selected_products = rng.sample(products, item_count)
        store_name, store_city = rng.choice(OFFLINE_STORES)
        order_rows = []
        for line_number, product in enumerate(selected_products, start=1):
            quantity = rng.choices((1, 2, 3, 4), weights=(62, 26, 10, 2), k=1)[0]
            row = {
                "order_id": order_id,
                "line_number": line_number,
                "order_date": order_date,
                "product": product,
                "product_text": product_description(product, channel["kind"], rng),
                "quantity": quantity,
                "unit_price": product["price"],
                "customer": customer,
                "status": status,
                "payment": rng.choices(PAYMENTS, weights=(28, 32, 14, 18, 8), k=1)[0],
                "store_name": store_name,
                "store_city": store_city,
                "quality_case": order_index == 0,
            }
            order_rows.append(row)

        # Satu kasus kualitas yang disengaja per kanal; semua business key tetap unik.
        quality_row = order_rows[0]
        if order_index == 0:
            if channel["kind"] == "shopee":
                quality_row["status"] = "IN_TRANSIT"
            elif channel["kind"] == "tokopedia":
                quality_row["quantity"] = 0
            elif channel["kind"] == "website":
                quality_row["bad_total"] = True
            else:
                quality_row["unmapped_product"] = True

        gross = sum((row["unit_price"] * row["quantity"] for row in order_rows), Decimal("0.00"))
        promotion = (
            None if order_index == 0 or status != "COMPLETED" else promotion_for_order(order_date, order_index, gross)
        )
        if promotion:
            code, discount = promotion
            redemptions.append(
                {
                    "source_name": channel["source"],
                    "order_id": order_id,
                    "promo_code": code,
                    "discount_amount": f"{discount:.2f}",
                }
            )

        for row in order_rows:
            row["promo_code"] = promotion[0] if promotion else ""
            row["discount_amount"] = "0.00"
            rows.append(row)
            cursor += 1

    if cursor != ROW_COUNT:
        raise AssertionError(f"{channel['source']} menghasilkan {cursor}, bukan {ROW_COUNT} baris")
    return rows, redemptions


def render_sales_row(row: dict, channel: dict) -> dict:
    kind = channel["kind"]
    description = row["product_text"]
    if row.get("unmapped_product"):
        description = "Produk Demo Tidak Terdaftar 50ml"
    date_value = row["order_date"].strftime(channel["date_format"])
    status = row["status"].lower() if row["line_number"] % 2 else row["status"]
    base = {
        "order_id": row["order_id"],
        "line": row["line_number"],
        "date": date_value,
        "product": description,
        "quantity": row["quantity"],
        "price": f"{row['unit_price']:.2f}",
        "status": status,
        "discount_amount": row["discount_amount"],
        "promo_code": row["promo_code"],
    }
    if kind == "shopee":
        return {
            "order_id": base["order_id"],
            "order_line_id": base["line"],
            "order_date": base["date"],
            "product_name": base["product"],
            "qty": base["quantity"],
            "unit_price": base["price"],
            "customer_name": row["customer"]["name"],
            "customer_city": row["customer"]["city"],
            "payment_method": row["payment"],
            "status": base["status"],
            "discount_amount": base["discount_amount"],
            "promo_code": base["promo_code"],
        }
    if kind == "tokopedia":
        return {
            "transaction_id": base["order_id"],
            "item_sequence": base["line"],
            "transaction_date": base["date"],
            "item_name": base["product"],
            "quantity": base["quantity"],
            "price": base["price"],
            "buyer_name": row["customer"]["name"],
            "city": row["customer"]["city"],
            "payment": row["payment"],
            "status": base["status"],
            "discount_amount": base["discount_amount"],
            "promo_code": base["promo_code"],
        }
    if kind == "website":
        total = Decimal("1") if row.get("bad_total") else row["unit_price"] * row["quantity"]
        return {
            "invoice_no": base["order_id"],
            "line_item_no": base["line"],
            "created_at": base["date"],
            "product_identifier": base["product"],
            "quantity": base["quantity"],
            "unit_price": base["price"],
            "total_amount": f"{total:.2f}",
            "customer_email": row["customer"]["email"],
            "status": base["status"],
            "discount_amount": base["discount_amount"],
            "promo_code": base["promo_code"],
        }
    return {
        "pos_receipt_no": base["order_id"],
        "receipt_line_no": base["line"],
        "sold_at": base["date"],
        "item_description": base["product"],
        "units": base["quantity"],
        "item_price": base["price"],
        "store_name": row["store_name"],
        "store_city": row["store_city"],
        "payment_type": row["payment"],
        "status": base["status"],
        "discount_amount": base["discount_amount"],
        "promo_code": base["promo_code"],
    }


def build_returns(source_dir: Path, built_rows: dict[str, list[dict]]) -> list[dict]:
    rng = random.Random(SEED + 900)
    old_rows = read_csv(source_dir / "returns.csv")
    result = []
    by_channel: dict[str, list[dict]] = {}
    for channel in CHANNELS:
        completed = [
            row for row in built_rows[channel["source"]] if row["status"] == "COMPLETED" and not row["quality_case"]
        ]
        rng.shuffle(completed)
        old = [
            row
            for row in old_rows
            if row.get("source_name", "").upper()
            in {channel["source"], "OFFLINE" if channel["source"] == "OFFLINE_STORE" else channel["source"]}
        ]
        event_keys = list(dict.fromkeys((row["return_id"], row["return_line_number"]) for row in old))
        while len(event_keys) < 12:
            next_id = f"RET-DEMO-{channel['prefix']}-2026-{len(event_keys) + 101:03}"
            event_keys.append((next_id, "1"))
        if len(completed) < len(event_keys):
            raise AssertionError(f"{channel['source']} tidak memiliki cukup baris completed untuk contoh retur")

        events = []
        for event_index, ((return_id, return_line_number), sale) in enumerate(zip(event_keys, completed)):
            qty = rng.randint(1, sale["quantity"])
            state = ("PENDING", "APPROVED", "PROCESSED", "PROCESSED", "REJECTED", "APPROVED")[event_index % 6]
            refund_state = {
                "PENDING": "PENDING",
                "APPROVED": "PENDING",
                "REJECTED": "NOT_APPLICABLE",
                "PROCESSED": "PROCESSED",
            }[state]
            refund = ""
            if refund_state == "PROCESSED":
                refund = f"{(sale['unit_price'] * qty * Decimal('0.60')).quantize(Decimal('0.01')):.2f}"
            return_date = sale["order_date"] + timedelta(days=rng.randint(2, 28))
            events.append(
                {
                    "source_name": channel["source"],
                    "return_id": return_id,
                    "return_line_number": return_line_number,
                    "order_id": sale["order_id"],
                    "order_line_number": sale["line_number"],
                    "return_date": return_date.isoformat(),
                    "return_reason": rng.choice(REASONS),
                    "return_status": state,
                    "quantity_returned": qty,
                    "refund_amount": refund,
                    "refund_status": refund_state,
                }
            )
        by_channel[channel["source"]] = events
        result.extend(events)
    return result


def generate(source_dir: Path, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    products = product_catalog(source_dir)
    customers = customer_profiles()
    all_sales, all_redemptions = {}, []
    for index, channel in enumerate(CHANNELS, start=1):
        rows, redemptions = build_channel(source_dir, channel, products, customers, index * 100)
        all_sales[channel["source"]] = rows
        all_redemptions.extend(redemptions)
        fields = (
            tuple(read_csv(source_dir / channel["filename"])[0]) if (source_dir / channel["filename"]).exists() else ()
        )
        if not fields:
            fields = {
                "shopee": (
                    "order_id",
                    "order_line_id",
                    "order_date",
                    "product_name",
                    "qty",
                    "unit_price",
                    "customer_name",
                    "customer_city",
                    "payment_method",
                    "status",
                    "discount_amount",
                    "promo_code",
                ),
                "tokopedia": (
                    "transaction_id",
                    "item_sequence",
                    "transaction_date",
                    "item_name",
                    "quantity",
                    "price",
                    "buyer_name",
                    "city",
                    "payment",
                    "status",
                    "discount_amount",
                    "promo_code",
                ),
                "website": (
                    "invoice_no",
                    "line_item_no",
                    "created_at",
                    "product_identifier",
                    "quantity",
                    "unit_price",
                    "total_amount",
                    "customer_email",
                    "status",
                    "discount_amount",
                    "promo_code",
                ),
                "offline": (
                    "pos_receipt_no",
                    "receipt_line_no",
                    "sold_at",
                    "item_description",
                    "units",
                    "item_price",
                    "store_name",
                    "store_city",
                    "payment_type",
                    "status",
                    "discount_amount",
                    "promo_code",
                ),
            }[channel["kind"]]
        write_csv(output_dir, channel["filename"], fields, [render_sales_row(row, channel) for row in rows])

    promo_fields = ("promo_code", "promo_name", "discount_type", "discount_value", "start_date", "end_date", "status")
    write_csv(output_dir, "promo_master.csv", promo_fields, [dict(zip(promo_fields, row)) for row in PROMOS])
    redemption_fields = ("source_name", "order_id", "promo_code", "discount_amount")
    write_csv(output_dir, "order_promotions.csv", redemption_fields, all_redemptions)
    return_fields = (
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
    write_csv(output_dir, "returns.csv", return_fields, build_returns(source_dir, all_sales))
    print(f"Data demo deterministik dibuat di: {output_dir}")
    print("Empat kanal: masing-masing 100 baris; setiap order memiliki 1 hingga 5 baris item.")
    print("Setiap kanal memiliki satu kasus kualitas terkendali; duplikat business key tidak dibuat.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-dir", type=Path, default=DEFAULT_DIR, help="Direktori input untuk katalog dan ID order lama"
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_DIR, help="Direktori output CSV demo")
    args = parser.parse_args()
    generate(args.source_dir, args.output_dir)


if __name__ == "__main__":
    main()
