-- Canonical analytics views over warehouse.fact_sales and dimensions.
CREATE OR REPLACE VIEW warehouse.v_sales_detail AS
SELECT
    f.sales_key,
    f.source_name,
    f.source_order_id AS order_id,
    f.source_line_number AS line_number,
    d.full_date AS order_date,
    p.sku AS product_id,
    p.product_name,
    p.brand,
    p.category,
    c.channel_name,
    f.sale_status AS status,
    cu.customer_name,
    cu.city,
    pm.payment_method,
    f.quantity,
    f.unit_price,
    f.gross_amount,
    f.discount_amount,
    f.net_amount,
    f.loaded_at
FROM warehouse.fact_sales f
JOIN warehouse.dim_date d ON d.date_key = f.date_key
JOIN warehouse.dim_product p ON p.product_key = f.product_key
JOIN warehouse.dim_channel c ON c.channel_key = f.channel_key
LEFT JOIN warehouse.dim_customer cu ON cu.customer_key = f.customer_key
LEFT JOIN warehouse.dim_payment pm ON pm.payment_key = f.payment_key;

CREATE OR REPLACE VIEW warehouse.v_sales_by_month AS
SELECT d.year_number, d.month_number, d.month_name, f.sale_status AS status,
       SUM(f.quantity) AS quantity_sold, COUNT(*) AS order_lines,
       SUM(f.gross_amount) AS gross_sales, SUM(f.net_amount) AS net_sales
FROM warehouse.fact_sales f
JOIN warehouse.dim_date d ON d.date_key = f.date_key
GROUP BY d.year_number, d.month_number, d.month_name, f.sale_status;

CREATE OR REPLACE VIEW warehouse.v_sales_by_channel AS
SELECT c.channel_code, c.channel_name, c.channel_type, f.sale_status AS status,
       COUNT(*) AS order_lines, SUM(f.quantity) AS quantity_sold,
       SUM(f.gross_amount) AS gross_sales, SUM(f.net_amount) AS net_sales
FROM warehouse.fact_sales f
JOIN warehouse.dim_channel c ON c.channel_key = f.channel_key
GROUP BY c.channel_code, c.channel_name, c.channel_type, f.sale_status;

CREATE OR REPLACE VIEW warehouse.v_sales_by_product AS
SELECT p.sku AS product_id, p.product_name, p.brand, p.category, f.sale_status AS status,
       COUNT(*) AS order_lines, SUM(f.quantity) AS quantity_sold,
       SUM(f.gross_amount) AS gross_sales, SUM(f.net_amount) AS net_sales
FROM warehouse.fact_sales f
JOIN warehouse.dim_product p ON p.product_key = f.product_key
GROUP BY p.sku, p.product_name, p.brand, p.category, f.sale_status;

CREATE OR REPLACE VIEW warehouse.v_pipeline_quality AS
SELECT r.run_id, r.started_at, r.ended_at, r.status,
       r.extracted_records, r.valid_records, r.duplicate_records,
       r.invalid_records, r.loaded_records, r.validated_records, r.rejected_records,
       r.incremental_records, r.staged_records, r.dimension_records,
       r.fact_inserted_records, r.fact_skipped_records, r.duration_seconds,
       COALESCE(SUM(CASE WHEN q.severity = 'ERROR' THEN q.failed_records ELSE 0 END), 0) AS error_records,
       COALESCE(SUM(CASE WHEN q.severity = 'WARNING' THEN q.failed_records ELSE 0 END), 0) AS warning_records
FROM audit.pipeline_runs r
LEFT JOIN audit.data_quality_results q ON q.run_id = r.run_id
GROUP BY r.run_id, r.started_at, r.ended_at, r.status, r.extracted_records,
         r.valid_records, r.duplicate_records, r.invalid_records, r.loaded_records;
