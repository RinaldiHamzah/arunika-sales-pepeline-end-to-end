"""Buat data contoh deterministik untuk ETL."""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "source"
SEED = 20260913
FIXED_ITEM_COUNTS = (1, 2, 3, 5, 10)
SAMPLE_LINE_COUNT = 50

# Katalog sintetis terinspirasi dari merek Paragon; SKU dan harga hanya contoh.
PRODUCTS = [
    ("WRD-SKC-001", "Wardah UV Shield Aqua Fresh Essence SPF 50 PA++++ 30ml", "Wardah", "Skincare", 68900),
    ("WRD-SKC-002", "Wardah Lightening Micellar Water 100ml", "Wardah", "Skincare", 28900),
    ("WRD-MUP-001", "Wardah Colorfit Velvet Matte Lip Mousse 03", "Wardah", "Makeup", 62900),
    ("WRD-MUP-002", "Wardah Colorfit Perfect Glow Cushion 13N", "Wardah", "Makeup", 109000),
    ("EMN-SKC-001", "Emina Bright Stuff Face Wash 100ml", "Emina", "Skincare", 27900),
    ("EMN-SKC-002", "Emina Sun Battle SPF 50 PA++++ 30ml", "Emina", "Skincare", 49900),
    ("EMN-MUP-001", "Emina Cheek Lit Cream Blush Peach", "Emina", "Makeup", 46900),
    ("EMN-MUP-002", "Emina Glossy Stain 01 Autumn Bell", "Emina", "Makeup", 52900),
    ("MKO-MUP-001", "Make Over Powerstay Weightless Liquid Foundation W22", "Make Over", "Makeup", 169000),
    ("MKO-MUP-002", "Make Over Powerstay Matte Powder Foundation N20", "Make Over", "Makeup", 179000),
    ("KHF-SKC-001", "Kahf Triple Protection Sunscreen Moisturizer SPF 30", "Kahf", "Mens Grooming", 54900),
    ("KHF-BDY-001", "Kahf Face Wash Oil and Comedo Defense 100ml", "Kahf", "Mens Grooming", 42900),
    ("LBR-SKC-001", "LABORE BiomeProtect Physical Sunscreen SPF 50 30ml", "LABORE", "Skincare", 129000),
    ("LBR-SKC-002", "LABORE Barrier Revive Cream 30ml", "LABORE", "Skincare", 119000),
    ("INS-MUP-001", "Instaperfect Skincover Air Cushion 02 Beige", "Instaperfect", "Makeup", 149000),
    ("CRY-SKC-001", "Crystallure Supreme Revitalizing Oil Serum 20ml", "Crystallure", "Skincare", 219000),
    ("TVI-SKC-001", "TAVI Urban Shield Sunscreen SPF 50 30ml", "TAVI", "Skincare", 89900),
    ("BDF-BDY-001", "Biodef Body Wash Fresh Care 450ml", "Biodef", "Body Care", 35900),
    ("WND-BDY-001", "Wonderly Body Mist Sweet Blossom 100ml", "Wonderly", "Fragrance", 45900),
    ("WRD-SKC-003", "Wardah Aloe Hydramild Moisturizer 40ml", "Wardah", "Skincare", 45900),
]
CUSTOMERS = [
    ("C001", "Alya Putri", "Jakarta"),
    ("C002", "Bima Pratama", "Bandung"),
    ("C003", "Citra Lestari", "Surabaya"),
    ("C004", "Dimas Saputra", "Yogyakarta"),
    ("C005", "Eka Wulandari", "Semarang"),
]


def records(offset: int) -> list[dict]:
    """Buat lima pesanan acuan dan pesanan acak dengan 1–10 item per pesanan."""
    rng = random.Random(SEED + offset)
    result: list[dict] = []
    order_index = 0
    while len(result) < SAMPLE_LINE_COUNT:
        count = FIXED_ITEM_COUNTS[order_index] if order_index < len(FIXED_ITEM_COUNTS) else rng.randint(1, 10)
        count = min(count, SAMPLE_LINE_COUNT - len(result))
        customer_id, customer, city = rng.choice(CUSTOMERS)
        order_date = date(2026, 1, 1) + timedelta(days=rng.randrange(240))
        payment = rng.choice(["Transfer Bank", "E-Wallet", "Credit Card", "COD"])
        status = rng.choice(["completed", "completed", "completed", "cancelled", "returned"])
        for line_number in range(1, count + 1):
            sku, product, _brand, _category, price = rng.choice(PRODUCTS)
            variants = [product, product.upper(), product.replace(" ", "-"), f" {product} "]
            result.append(
                {
                    "id": offset + order_index,
                    "line_number": line_number,
                    "date": order_date,
                    "sku": sku,
                    "name": rng.choice(variants),
                    "qty": rng.choice([1, 1, 2, 3]),
                    "price": price,
                    "customer_id": customer_id,
                    "customer": customer,
                    "city": city,
                    "payment": payment,
                    "status": status,
                    "customer_email": f"{customer.lower().replace(' ', '.')}@example.test",
                }
            )
        order_index += 1

    # Cacat kualitas dibuat secara terkontrol, satu untuk setiap jenis pada tiap sumber.
    result[22]["qty"] = 0
    result[24]["price"] = -50000
    result[26]["customer"] = ""
    result[28]["city"] = ""
    result[30]["payment"] = ""
    result[32]["status"] = "in_progress"
    result[34]["name"] = "Brigthning Serumm 30ml"
    result[36]["date"] = "not-a-date"
    result[40]["source_total_amount"] = 1  # Cacat khusus Website: total tidak sesuai dengan quantity × harga.
    result[38]["qty"] = 2
    result[38]["price"] = 100
    result[38]["sku"] = PRODUCTS[0][0]
    result[38]["name"] = PRODUCTS[0][1]
    result[38]["date"] = date(2026, 3, 1)
    result[38]["status"] = "completed"
    result.append(result[38].copy())  # Duplikat persis, terpisah dari lima pesanan acuan.
    conflict = result[39].copy()
    conflict["qty"] = int(conflict["qty"]) + 1
    result.append(conflict)
    return result


def write(name: str, fields: list[str], rows: list[dict], convert) -> None:
    with (OUT / name).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(convert(r) for r in rows)


def format_date(value, pattern: str):
    """Format nilai tanggal sambil mempertahankan nilai uji yang sengaja dibuat tidak valid."""
    return value.strftime(pattern) if isinstance(value, date) else value


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    shopee_rows, tokopedia_rows, website_rows, offline_rows = records(1), records(101), records(201), records(301)
    fmt = format_date

    write(
        "shopee.csv",
        [
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
        ],
        shopee_rows,
        lambda r: {
            "order_id": f"SHP-{r['id']:04}",
            "order_line_id": r["line_number"],
            "order_date": fmt(r["date"], "%Y-%m-%d"),
            "product_name": r["name"],
            "qty": r["qty"],
            "unit_price": r["price"],
            "customer_name": r["customer"],
            "customer_city": r["city"],
            "payment_method": r["payment"],
            "status": r["status"],
        },
    )

    write(
        "tokopedia.csv",
        [
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
        ],
        tokopedia_rows,
        lambda r: {
            "transaction_id": f"TKP-{r['id']:04}",
            "item_sequence": r["line_number"],
            "transaction_date": fmt(r["date"], "%d/%m/%Y"),
            "item_name": r["name"],
            "quantity": r["qty"],
            "price": r["price"],
            "buyer_name": r["customer"],
            "city": r["city"],
            "payment": r["payment"],
            "status": r["status"],
        },
    )

    write(
        "website.csv",
        [
            "invoice_no",
            "line_item_no",
            "created_at",
            "product_identifier",
            "quantity",
            "unit_price",
            "total_amount",
            "customer_email",
            "status",
        ],
        website_rows,
        lambda r: {
            "invoice_no": f"WEB-{r['id']:04}",
            "line_item_no": r["line_number"],
            "created_at": fmt(r["date"], "%Y-%m-%dT10:30:00"),
            "product_identifier": r["sku"],
            "quantity": r["qty"],
            "unit_price": r["price"],
            "total_amount": r.get("source_total_amount", r["qty"] * r["price"]),
            "customer_email": r["customer_email"],
            "status": r["status"],
        },
    )

    write(
        "offline.csv",
        [
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
        ],
        offline_rows,
        lambda r: {
            "pos_receipt_no": f"POS-{r['id']:04}",
            "receipt_line_no": r["line_number"],
            "sold_at": fmt(r["date"], "%d-%b-%Y"),
            "item_description": r["name"],
            "units": r["qty"],
            "item_price": r["price"],
            "store_name": "Arunika Beauty Store",
            "store_city": r["city"],
            "payment_type": r["payment"],
            "status": r["status"],
        },
    )

    write(
        "product.csv",
        ["sku", "product_name", "brand", "category", "price"],
        [dict(zip(["sku", "product_name", "brand", "category", "price"], product)) for product in PRODUCTS],
        lambda r: r,
    )

    print(f"Generated source files in {OUT}")


if __name__ == "__main__":
    main()
