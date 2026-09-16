"""Generate deterministic, deliberately imperfect input files for the ETL."""
from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parents[1] / "data" / "source"
RNG = random.Random(20260913)
# Synthetic catalogue inspired by Paragon brands; SKU and price are fictional.
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
CUSTOMERS = [("C001", "Alya Putri", "Jakarta"), ("C002", "Bima Pratama", "Bandung"), ("C003", "Citra Lestari", "Surabaya"), ("C004", "Dimas Saputra", "Yogyakarta"), ("C005", "Eka Wulandari", "Semarang")]


def records(offset: int) -> list[dict]:
    result = []
    for i in range(50):
        sku, product, brand, category, price = RNG.choice(PRODUCTS)
        customer_id, customer, city = RNG.choice(CUSTOMERS)
        variants = [product, product.upper(), product.replace(" ", "-"), f" {product} "]
        result.append({"id": offset + i, "date": date(2026, 1, 1) + timedelta(days=RNG.randrange(240)), "sku": sku, "name": RNG.choice(variants), "qty": RNG.choice([1, 1, 2, 3]), "price": price, "customer_id": customer_id, "customer": customer, "city": city, "payment": RNG.choice(["Transfer Bank", "E-Wallet", "Credit Card", "COD"]), "status": RNG.choice(["completed", "completed", "completed", "cancelled", "returned"])})
    # Controlled quality defects, one of each type per source.
    result[3]["qty"] = 0; result[7]["price"] = -50000; result[11]["customer"] = ""
    result[15]["city"] = ""; result[19]["payment"] = ""; result[23]["status"] = "in_progress"
    result[27]["name"] = "Brigthning Serumm 30ml"; result[31]["date"] = "not-a-date"
    result.append(result[5].copy())
    return result


def write(name: str, fields: list[str], rows: list[dict], convert) -> None:
    with (OUT / name).open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        writer.writerows(convert(r) for r in rows)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    a, b, web, offline = records(1), records(101), records(201), records(301)
    fmt = lambda v, pattern: v.strftime(pattern) if isinstance(v, date) else v
    write("shopee.csv", ["order_id", "order_date", "product_name", "qty", "unit_price", "customer_name", "customer_city", "payment_method", "order_status"], a, lambda r: {"order_id": f"SHP-{r['id']:04}", "order_date": fmt(r["date"], "%Y-%m-%d"), "product_name": r["name"], "qty": r["qty"], "unit_price": r["price"], "customer_name": r["customer"], "customer_city": r["city"], "payment_method": r["payment"], "order_status": r["status"]})
    write("tokopedia.csv", ["transaction_id", "transaction_date", "item_name", "quantity", "price", "buyer_name", "city", "payment", "status"], b, lambda r: {"transaction_id": f"TKP-{r['id']:04}", "transaction_date": fmt(r["date"], "%d/%m/%Y"), "item_name": r["name"], "quantity": r["qty"], "price": r["price"], "buyer_name": r["customer"], "city": r["city"], "payment": r["payment"], "status": r["status"]})
    write("website.csv", ["invoice_no", "created_at", "sku", "customer_id", "customer_name", "quantity", "selling_price", "payment_method", "status"], web, lambda r: {"invoice_no": f"WEB-{r['id']:04}", "created_at": fmt(r["date"], "%Y-%m-%dT10:30:00"), "sku": r["sku"], "customer_id": r["customer_id"], "customer_name": r["customer"], "quantity": r["qty"], "selling_price": r["price"], "payment_method": r["payment"], "status": r["status"]})
    write("offline_store.csv", ["pos_receipt_no", "sold_at", "item_description", "units", "item_price", "store_name", "store_city", "payment_type", "sale_status"], offline, lambda r: {"pos_receipt_no": f"POS-{r['id']:04}", "sold_at": fmt(r["date"], "%d-%b-%Y"), "item_description": r["name"], "units": r["qty"], "item_price": r["price"], "store_name": "Paragon Beauty Store", "store_city": r["city"], "payment_type": r["payment"], "sale_status": r["status"]})
    write("product_master.csv", ["sku", "product_name", "brand", "category", "price"], [dict(zip(["sku", "product_name", "brand", "category", "price"], p)) for p in PRODUCTS], lambda r: r)
    print(f"Generated source files in {OUT}")


if __name__ == "__main__": main()
