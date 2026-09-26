"""Publish reusable SQL KPI and data-quality reporting views."""

from alembic import op

revision = "20260925_08"
down_revision = "20260922_07"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
-- PostgreSQL CREATE OR REPLACE VIEW cannot remove or reorder columns. The
-- bootstrap SQL may already contain a newer shape, so recreate these views.
DROP VIEW IF EXISTS audit.v_data_quality_report;
DROP VIEW IF EXISTS audit.v_data_quality_by_rule;
DROP VIEW IF EXISTS warehouse.v_sales_status_kpi;
DROP VIEW IF EXISTS warehouse.v_top_product_kpi;
DROP VIEW IF EXISTS warehouse.v_sales_channel_kpi;
DROP VIEW IF EXISTS warehouse.v_sales_monthly_kpi;
DROP VIEW IF EXISTS warehouse.v_sales_kpi;

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
FROM warehouse.fact_sales;

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
GROUP BY c.channel_code, c.channel_name, c.channel_type;

CREATE OR REPLACE VIEW warehouse.v_top_product_kpi AS
SELECT p.sku AS product_id, p.product_name, p.brand, p.category,
       COALESCE(SUM(f.gross_amount), 0) AS gross_sales_all_statuses,
       COALESCE(SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED'), 0) AS net_sales_completed,
       COALESCE(SUM(f.quantity) FILTER (WHERE f.sale_status = 'COMPLETED'), 0) AS completed_units,
       COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED') AS completed_orders
FROM warehouse.fact_sales f JOIN warehouse.dim_product p ON p.product_key = f.product_key
GROUP BY p.sku, p.product_name, p.brand, p.category;

CREATE OR REPLACE VIEW warehouse.v_sales_status_kpi AS
SELECT sale_status, COUNT(DISTINCT source_name || '|' || source_order_id) AS orders,
       COALESCE(SUM(quantity), 0) AS units, COALESCE(SUM(gross_amount), 0) AS gross_sales,
       COALESCE(SUM(net_amount), 0) AS net_sales
FROM warehouse.fact_sales GROUP BY sale_status;

CREATE OR REPLACE VIEW audit.v_data_quality_by_rule AS
SELECT r.run_id, r.pipeline_name, r.started_at, r.status AS pipeline_status,
       q.source_name, q.rule_name, q.severity, SUM(q.failed_records) AS failed_records,
       MAX(q.evaluated_at) AS evaluated_at
FROM audit.data_quality_results q JOIN audit.pipeline_runs r ON r.run_id = q.run_id
GROUP BY r.run_id, r.pipeline_name, r.started_at, r.status,
         q.source_name, q.rule_name, q.severity;
    """)


def downgrade():
    op.execute("""
DROP VIEW IF EXISTS audit.v_data_quality_by_rule;
DROP VIEW IF EXISTS warehouse.v_sales_status_kpi;
DROP VIEW IF EXISTS warehouse.v_top_product_kpi;
DROP VIEW IF EXISTS warehouse.v_sales_channel_kpi;
DROP VIEW IF EXISTS warehouse.v_sales_monthly_kpi;
DROP VIEW IF EXISTS warehouse.v_sales_kpi;
    """)
