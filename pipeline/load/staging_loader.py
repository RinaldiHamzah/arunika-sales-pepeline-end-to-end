"""Load validated canonical rows into the staging table."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection


RAW_TABLES = {
    "SHOPEE": "raw.shopee_orders",
    "TOKOPEDIA": "raw.tokopedia_transactions",
    "WEBSITE": "raw.website_transactions",
    "OFFLINE_STORE": "raw.offline_store_sales",
}


def _raw_record_ids(connection: Connection, run_id: UUID) -> dict[tuple[str, int], int]:
    records = {}
    for source_name, table in RAW_TABLES.items():
        rows = connection.execute(text(
            f"SELECT raw_record_id, source_row_number FROM {table} WHERE ingestion_run_id = :run_id"
        ), {"run_id": str(run_id)}).mappings()
        records.update({(source_name, row["source_row_number"]): row["raw_record_id"] for row in rows})
        # Idempotent raw ingestion may reuse an existing row from an earlier
        # run.  Fall back to the latest raw record so staging is not coupled
        # to the current audit run id.
        rows = connection.execute(text(
            f"SELECT raw_record_id, source_row_number FROM {table} ORDER BY raw_record_id DESC"
        )).mappings()
        for row in rows:
            records.setdefault((source_name, row["source_row_number"]), row["raw_record_id"])
    return records


def load_staging(connection: Connection, run_id: UUID, rows) -> int:
    """Insert clean rows once for the ingestion run and return inserted candidates."""
    raw_ids = _raw_record_ids(connection, run_id)
    records = []
    for row in rows.to_dict("records"):
        raw_id = raw_ids.get((row["source_name"], row["source_row_number"]))
        if raw_id is None:
            raise ValueError(f"Raw record not found for {row['source_name']} row {row['source_row_number']}")
        record = dict(row)
        record.update({"ingestion_run_id": str(run_id), "source_raw_record_id": raw_id})
        records.append(record)
    if not records:
        return 0
    statement = text("""
        INSERT INTO staging.stg_sales (
            ingestion_run_id, source_name, source_raw_record_id, source_order_id,
            source_line_number, order_date, product_input, mapped_sku, customer_nk,
            customer_name, city, payment_method, sale_status, quantity, unit_price,
            source_total_amount, source_record_hash
        ) VALUES (
            :ingestion_run_id, :source_name, :source_raw_record_id, :source_order_id,
            :source_line_number, :order_date, :product_input, :mapped_sku, :customer_nk,
            :customer_name, :city, :payment_method, :sale_status, :quantity, :unit_price,
            :source_total_amount, :source_record_hash
        ) ON CONFLICT (source_name, source_order_id, source_line_number) DO UPDATE SET
            ingestion_run_id = EXCLUDED.ingestion_run_id,
            source_raw_record_id = EXCLUDED.source_raw_record_id,
            order_date = EXCLUDED.order_date, product_input = EXCLUDED.product_input,
            mapped_sku = EXCLUDED.mapped_sku, customer_nk = EXCLUDED.customer_nk,
            customer_name = EXCLUDED.customer_name, city = EXCLUDED.city,
            payment_method = EXCLUDED.payment_method, sale_status = EXCLUDED.sale_status,
            quantity = EXCLUDED.quantity, unit_price = EXCLUDED.unit_price,
            source_total_amount = EXCLUDED.source_total_amount,
            source_record_hash = EXCLUDED.source_record_hash,
            transformed_at = CURRENT_TIMESTAMP
    """)
    result = connection.execute(statement, records)
    return result.rowcount
