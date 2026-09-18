"""Incremental fact loader with dimension-key resolution."""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection


def load_facts(connection: Connection, run_id: UUID) -> int:
	"""Load valid staging rows into fact_sales without duplicate business keys."""
	result = connection.execute(text("""
		INSERT INTO warehouse.fact_sales (
			source_name, source_order_id, source_line_number, date_key, product_key,
			customer_key, channel_key, payment_key, sale_status, quantity, unit_price,
			gross_amount, discount_amount, net_amount, source_record_hash, is_source_active
		)
		SELECT
			s.source_name, s.source_order_id, s.source_line_number,
			d.date_key, p.product_key, c.customer_key, ch.channel_key, pm.payment_key,
			s.sale_status, s.quantity, s.unit_price, s.gross_amount,
			0, s.gross_amount, s.source_record_hash, TRUE
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
			gross_amount = EXCLUDED.gross_amount, net_amount = EXCLUDED.net_amount,
			source_record_hash = EXCLUDED.source_record_hash,
			is_source_active = TRUE, loaded_at = CURRENT_TIMESTAMP
	"""), {"run_id": str(run_id)})
	return result.rowcount
