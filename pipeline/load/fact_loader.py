"""Pemuat fact secara inkremental."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from pipeline.validation.contracts import SOURCE_NAMES, SOURCE_SPECS
from pipeline.validation.rules import clean_text


def _snapshot_business_keys(source):
    """Ambil business key dari snapshot lengkap, termasuk baris yang field lain invalid."""
    source_key = next((key for key, name in SOURCE_NAMES.items() if name == source.source_name), None)
    if source_key is None:
        return None, "sumber bukan kanal transaksi"
    if source.source_records is not None and len(source.frame) != source.source_records:
        return None, "snapshot sumber tidak lengkap"

    spec = SOURCE_SPECS[source_key]
    required = (spec["order_id"], spec["line_number"])
    if any(column not in source.frame.columns for column in required):
        return None, "kolom business key tidak tersedia"

    keys = set()
    for row in source.frame.to_dict("records"):
        order_id = clean_text(row.get(spec["order_id"]))
        line_value = clean_text(row.get(spec["line_number"]))
        line_text = line_value or ""
        if not order_id or not line_text.isdecimal():
            return None, "ada baris dengan business key yang tidak dapat ditentukan"
        line_number = int(line_text)
        if not 0 < line_number <= 2147483647:
            return None, "ada nomor baris di luar batas yang didukung"
        keys.add((order_id, line_number))
    return keys, None


def reconcile_source_snapshot(connection: Connection, run_id: UUID, sources) -> list[dict]:
    """Tandai fact yang hilang dari snapshot penuh tanpa menghapus riwayat warehouse."""
    summaries = []
    for source in sources:
        keys, skip_reason = _snapshot_business_keys(source)
        if skip_reason:
            connection.execute(
                text("""
                    INSERT INTO audit.source_reconciliations
                        (run_id, source_name, status, source_records,
                         observed_business_keys, deactivated_records, detail)
                    VALUES (:run_id, :source_name, 'SKIPPED', :source_records, 0, 0, :detail)
                    ON CONFLICT (run_id, source_name) DO UPDATE SET
                        status = EXCLUDED.status,
                        source_records = EXCLUDED.source_records,
                        observed_business_keys = 0,
                        deactivated_records = 0,
                        detail = EXCLUDED.detail,
                        reconciled_at = CURRENT_TIMESTAMP
                """),
                {
                    "run_id": str(run_id),
                    "source_name": source.source_name,
                    "source_records": source.source_records if source.source_records is not None else len(source.frame),
                    "detail": skip_reason,
                },
            )
            summaries.append({
                "source_name": source.source_name,
                "status": "SKIPPED",
                "reason": skip_reason,
                "source_records": source.source_records if source.source_records is not None else len(source.frame),
                "observed_business_keys": 0,
                "deactivated_records": 0,
            })
            continue

        source_name = source.source_name
        ordered_keys = sorted(keys)
        order_ids = [key[0] for key in ordered_keys]
        line_numbers = [key[1] for key in ordered_keys]
        result = connection.execute(
            text("""
                UPDATE warehouse.fact_sales AS fact
                SET is_source_active = FALSE
                WHERE fact.source_name = :source_name
                  AND fact.is_source_active = TRUE
                  AND NOT EXISTS (
                      SELECT 1
                      FROM unnest(CAST(:order_ids AS TEXT[]), CAST(:line_numbers AS INTEGER[]))
                           AS current_source(order_id, line_number)
                      WHERE current_source.order_id = fact.source_order_id
                        AND current_source.line_number = fact.source_line_number
                  )
            """),
            {"source_name": source_name, "order_ids": order_ids, "line_numbers": line_numbers},
        )
        deactivated = max(result.rowcount or 0, 0)
        status = "SUCCESS"
        connection.execute(
            text("""
                INSERT INTO audit.source_reconciliations
                    (run_id, source_name, status, source_records,
                     observed_business_keys, deactivated_records, detail)
                VALUES (:run_id, :source_name, :status, :source_records,
                        :observed, :deactivated, NULL)
                ON CONFLICT (run_id, source_name) DO UPDATE SET
                    status = EXCLUDED.status,
                    source_records = EXCLUDED.source_records,
                    observed_business_keys = EXCLUDED.observed_business_keys,
                    deactivated_records = EXCLUDED.deactivated_records,
                    detail = EXCLUDED.detail,
                    reconciled_at = CURRENT_TIMESTAMP
            """),
            {
                "run_id": str(run_id),
                "source_name": source_name,
                "status": status,
                "source_records": source.source_records if source.source_records is not None else len(source.frame),
                "observed": len(keys),
                "deactivated": deactivated,
            },
        )
        summaries.append({
            "source_name": source_name,
            "status": status,
            "source_records": source.source_records if source.source_records is not None else len(source.frame),
            "observed_business_keys": len(keys),
            "deactivated_records": deactivated,
        })
    return summaries


def load_facts(connection: Connection, run_id: UUID) -> int:
    """Muat baris staging valid ke fact_sales tanpa menggandakan business key."""
    result = connection.execute(
        text("""
		INSERT INTO warehouse.fact_sales (
			source_name, source_order_id, source_line_number, date_key, product_key,
			customer_key, channel_key, payment_key, sale_status, quantity, unit_price,
			gross_amount, discount_amount, net_amount, promo_code, source_record_hash, is_source_active
		)
		SELECT
			s.source_name, s.source_order_id, s.source_line_number,
			d.date_key, p.product_key, c.customer_key, ch.channel_key, pm.payment_key,
			s.sale_status, s.quantity, s.unit_price, s.gross_amount,
			s.discount_amount, s.net_amount, s.promo_code, s.source_record_hash, TRUE
		FROM staging.stg_sales s
		JOIN warehouse.dim_date d ON d.full_date = s.order_date
		JOIN warehouse.dim_product p ON p.sku = s.mapped_sku
		JOIN warehouse.dim_channel ch ON ch.channel_code = s.source_name
		LEFT JOIN warehouse.dim_customer c ON c.customer_nk = s.customer_nk
		LEFT JOIN warehouse.dim_payment pm ON pm.payment_method = s.payment_method
		WHERE s.ingestion_run_id = :run_id AND s.is_valid
		ON CONFLICT (source_name, source_order_id, source_line_number) DO UPDATE SET
			date_key = EXCLUDED.date_key, product_key = EXCLUDED.product_key,
			customer_key = EXCLUDED.customer_key, channel_key = EXCLUDED.channel_key,
			payment_key = EXCLUDED.payment_key, sale_status = EXCLUDED.sale_status,
			quantity = EXCLUDED.quantity, unit_price = EXCLUDED.unit_price,
			gross_amount = EXCLUDED.gross_amount, discount_amount = EXCLUDED.discount_amount,
			net_amount = EXCLUDED.net_amount, promo_code = EXCLUDED.promo_code,
			source_record_hash = EXCLUDED.source_record_hash,
			is_source_active = TRUE, loaded_at = CURRENT_TIMESTAMP
		WHERE warehouse.fact_sales.source_record_hash IS DISTINCT FROM EXCLUDED.source_record_hash OR warehouse.fact_sales.is_source_active IS DISTINCT FROM TRUE
	"""),
        {"run_id": str(run_id)},
    )
    return result.rowcount
