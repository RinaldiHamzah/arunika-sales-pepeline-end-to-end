"""Idempotent upsert loader for warehouse dimensions."""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.engine import Connection


def load_dimensions(connection: Connection, product_rows, staging_rows) -> dict[str, int]:
    """Upsert dimensions from validated product and staging rows."""
    products = product_rows.to_dict("records")
    if products:
        connection.execute(
            text("""
                INSERT INTO warehouse.dim_product (sku, product_name, brand, category, standard_price)
                VALUES (:sku, :product_name, :brand, :category, :price)
                ON CONFLICT (sku) DO UPDATE SET
                    product_name = EXCLUDED.product_name,
                    brand = EXCLUDED.brand,
                    category = EXCLUDED.category,
                    standard_price = EXCLUDED.standard_price,
                    updated_at = CURRENT_TIMESTAMP
            """),
            products,
        )

    dates, customers, payments = {}, {}, set()
    for row in staging_rows.to_dict("records"):
        date_value = row["order_date"]
        dates[date_value] = {
            "date_key": int(date_value.strftime("%Y%m%d")),
            "full_date": date_value,
            "day_of_month": date_value.day,
            "month_number": date_value.month,
            "month_name": date_value.strftime("%B"),
            "quarter_number": (date_value.month - 1) // 3 + 1,
            "year_number": date_value.year,
            "day_name": date_value.strftime("%A"),
            "is_weekend": date_value.weekday() >= 5,
        }
        if row.get("customer_nk"):
            customer_key = row["customer_nk"]
            existing_customer = customers.get(customer_key, {})
            customers[customer_key] = {
                "customer_nk": row["customer_nk"],
                "customer_name": row.get("customer_name") or existing_customer.get("customer_name"),
                # A valid city seen earlier in the same batch remains the
                # source-of-record when another line for that exact customer
                # omits the optional location field.
                "city": row.get("city") or existing_customer.get("city"),
            }
        if row.get("payment_method"):
            payments.add(row["payment_method"])

    if dates:
        connection.execute(
            text("""
                INSERT INTO warehouse.dim_date
                    (date_key, full_date, day_of_month, month_number, month_name,
                     quarter_number, year_number, day_name, is_weekend)
                VALUES (:date_key, :full_date, :day_of_month, :month_number, :month_name,
                        :quarter_number, :year_number, :day_name, :is_weekend)
                ON CONFLICT (date_key) DO NOTHING
            """),
            list(dates.values()),
        )
    if customers:
        connection.execute(
            text("""
                INSERT INTO warehouse.dim_customer (customer_nk, customer_name, city)
                VALUES (:customer_nk, :customer_name, :city)
                ON CONFLICT (customer_nk) DO UPDATE SET
                    customer_name = COALESCE(EXCLUDED.customer_name, warehouse.dim_customer.customer_name),
                    -- Do not erase a previously verified city when a later
                    -- source row has no location.  This is deterministic
                    -- enrichment by the exact customer natural key, not a
                    -- geographic guess.
                    city = CASE
                        WHEN EXCLUDED.city IS NULL
                          OR LOWER(BTRIM(EXCLUDED.city)) IN ('', 'nan', 'none', 'null', 'n/a', 'na')
                            THEN warehouse.dim_customer.city
                        ELSE EXCLUDED.city
                    END,
                    updated_at = CURRENT_TIMESTAMP
            """),
            list(customers.values()),
        )
    if payments:
        connection.execute(
            text("""
                INSERT INTO warehouse.dim_payment (payment_method)
                VALUES (:payment_method)
                ON CONFLICT (payment_method) DO NOTHING
            """),
            [{"payment_method": value} for value in payments],
        )
    return {
        "products": len(products),
        "dates": len(dates),
        "customers": len(customers),
        "payments": len(payments),
    }
