"""Rekonsiliasi transaksi yang hilang dari snapshot sumber penuh."""

from alembic import op

revision = "20261109_15"
down_revision = "20261109_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.source_reconciliations (
            reconciliation_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
            source_name VARCHAR(30) NOT NULL,
            status VARCHAR(20) NOT NULL CHECK (status IN ('SUCCESS', 'SKIPPED')),
            source_records BIGINT NOT NULL CHECK (source_records >= 0),
            observed_business_keys BIGINT NOT NULL CHECK (observed_business_keys >= 0),
            deactivated_records BIGINT NOT NULL DEFAULT 0 CHECK (deactivated_records >= 0),
            detail TEXT,
            reconciled_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_source_reconciliation_run UNIQUE (run_id, source_name)
        );
        CREATE INDEX IF NOT EXISTS idx_source_reconciliations_source_time
            ON audit.source_reconciliations (source_name, reconciled_at DESC);

        CREATE OR REPLACE VIEW warehouse.v_sales_detail AS
        SELECT f.sales_key, f.source_name, f.source_order_id AS order_id,
               f.source_line_number AS line_number, d.full_date AS order_date,
               p.sku AS product_id, p.product_name, p.brand, p.category,
               c.channel_name, f.sale_status AS status, cu.customer_name, cu.city,
               pm.payment_method, f.quantity, f.unit_price, f.gross_amount,
               f.discount_amount, f.net_amount, f.loaded_at, f.promo_code
        FROM warehouse.fact_sales f
        JOIN warehouse.dim_date d ON d.date_key = f.date_key
        JOIN warehouse.dim_product p ON p.product_key = f.product_key
        JOIN warehouse.dim_channel c ON c.channel_key = f.channel_key
        LEFT JOIN warehouse.dim_customer cu ON cu.customer_key = f.customer_key
        LEFT JOIN warehouse.dim_payment pm ON pm.payment_key = f.payment_key
        WHERE f.is_source_active;

        CREATE OR REPLACE VIEW warehouse.v_sales_by_month AS
        SELECT d.year_number, d.month_number, d.month_name, f.sale_status AS status,
               SUM(f.quantity) AS quantity_sold, COUNT(*) AS order_lines,
               SUM(f.gross_amount) AS gross_sales, SUM(f.net_amount) AS net_sales
        FROM warehouse.fact_sales f JOIN warehouse.dim_date d ON d.date_key = f.date_key
        WHERE f.is_source_active
        GROUP BY d.year_number, d.month_number, d.month_name, f.sale_status;

        CREATE OR REPLACE VIEW warehouse.v_sales_by_channel AS
        SELECT c.channel_code, c.channel_name, c.channel_type, f.sale_status AS status,
               COUNT(*) AS order_lines, SUM(f.quantity) AS quantity_sold,
               SUM(f.gross_amount) AS gross_sales, SUM(f.net_amount) AS net_sales
        FROM warehouse.fact_sales f JOIN warehouse.dim_channel c ON c.channel_key = f.channel_key
        WHERE f.is_source_active
        GROUP BY c.channel_code, c.channel_name, c.channel_type, f.sale_status;

        CREATE OR REPLACE VIEW warehouse.v_sales_by_product AS
        SELECT p.sku AS product_id, p.product_name, p.brand, p.category,
               f.sale_status AS status, COUNT(*) AS order_lines,
               SUM(f.quantity) AS quantity_sold, SUM(f.gross_amount) AS gross_sales,
               SUM(f.net_amount) AS net_sales
        FROM warehouse.fact_sales f JOIN warehouse.dim_product p ON p.product_key = f.product_key
        WHERE f.is_source_active
        GROUP BY p.sku, p.product_name, p.brand, p.category, f.sale_status;

        CREATE OR REPLACE VIEW warehouse.v_sales_kpi AS
        SELECT COALESCE(SUM(gross_amount), 0) AS gross_sales_all_statuses,
               COALESCE(SUM(net_amount) FILTER (WHERE sale_status = 'COMPLETED'), 0) AS net_sales_completed,
               COUNT(DISTINCT source_name || '|' || source_order_id) AS total_orders_all_statuses,
               COUNT(DISTINCT source_name || '|' || source_order_id) FILTER (WHERE sale_status = 'COMPLETED') AS completed_orders,
               COUNT(DISTINCT source_name || '|' || source_order_id) FILTER (WHERE sale_status = 'RETURNED') AS returned_orders,
               COALESCE(SUM(quantity) FILTER (WHERE sale_status = 'COMPLETED'), 0) AS completed_units,
               ROUND(100.0 * COUNT(DISTINCT source_name || '|' || source_order_id) FILTER (WHERE sale_status = 'RETURNED')
                     / NULLIF(COUNT(DISTINCT source_name || '|' || source_order_id), 0), 2) AS return_rate_pct,
               ROUND(SUM(net_amount) FILTER (WHERE sale_status = 'COMPLETED')
                     / NULLIF(COUNT(DISTINCT source_name || '|' || source_order_id) FILTER (WHERE sale_status = 'COMPLETED'), 0), 2) AS average_order_value
        FROM warehouse.fact_sales WHERE is_source_active;

        CREATE OR REPLACE VIEW warehouse.v_sales_monthly_kpi AS
        SELECT DATE_TRUNC('month', d.full_date)::date AS month_start,
               COALESCE(SUM(f.gross_amount), 0) AS gross_sales_all_statuses,
               COALESCE(SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED'), 0) AS net_sales_completed,
               COUNT(DISTINCT f.source_name || '|' || f.source_order_id) AS total_orders_all_statuses,
               COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED') AS completed_orders,
               COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'RETURNED') AS returned_orders,
               ROUND(100.0 * COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'RETURNED')
                     / NULLIF(COUNT(DISTINCT f.source_name || '|' || f.source_order_id), 0), 2) AS return_rate_pct,
               ROUND(SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED')
                     / NULLIF(COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED'), 0), 2) AS average_order_value
        FROM warehouse.fact_sales f JOIN warehouse.dim_date d ON d.date_key = f.date_key
        WHERE f.is_source_active
        GROUP BY DATE_TRUNC('month', d.full_date)::date;

        CREATE OR REPLACE VIEW warehouse.v_sales_channel_kpi AS
        SELECT c.channel_code, c.channel_name, c.channel_type,
               COALESCE(SUM(f.gross_amount), 0) AS gross_sales_all_statuses,
               COALESCE(SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED'), 0) AS net_sales_completed,
               COUNT(DISTINCT f.source_name || '|' || f.source_order_id) AS total_orders_all_statuses,
               COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED') AS completed_orders,
               COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'RETURNED') AS returned_orders,
               ROUND(100.0 * COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'RETURNED')
                     / NULLIF(COUNT(DISTINCT f.source_name || '|' || f.source_order_id), 0), 2) AS return_rate_pct,
               ROUND(SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED')
                     / NULLIF(COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED'), 0), 2) AS average_order_value
        FROM warehouse.fact_sales f JOIN warehouse.dim_channel c ON c.channel_key = f.channel_key
        WHERE f.is_source_active
        GROUP BY c.channel_code, c.channel_name, c.channel_type;

        CREATE OR REPLACE VIEW warehouse.v_top_product_kpi AS
        SELECT p.sku AS product_id, p.product_name, p.brand, p.category,
               COALESCE(SUM(f.gross_amount), 0) AS gross_sales_all_statuses,
               COALESCE(SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED'), 0) AS net_sales_completed,
               COALESCE(SUM(f.quantity) FILTER (WHERE f.sale_status = 'COMPLETED'), 0) AS completed_units,
               COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED') AS completed_orders
        FROM warehouse.fact_sales f JOIN warehouse.dim_product p ON p.product_key = f.product_key
        WHERE f.is_source_active
        GROUP BY p.sku, p.product_name, p.brand, p.category;

        CREATE OR REPLACE VIEW warehouse.v_sales_status_kpi AS
        SELECT sale_status, COUNT(DISTINCT source_name || '|' || source_order_id) AS orders,
               COALESCE(SUM(quantity), 0) AS units, COALESCE(SUM(gross_amount), 0) AS gross_sales,
               COALESCE(SUM(net_amount), 0) AS net_sales
        FROM warehouse.fact_sales WHERE is_source_active GROUP BY sale_status;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit.source_reconciliations")
