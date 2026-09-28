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

-- KPI definitions shared by SQL consumers and the dashboard documentation.
-- Gross is every transaction status; net revenue is completed orders only.
CREATE OR REPLACE VIEW warehouse.v_sales_kpi AS
SELECT
    COALESCE(SUM(gross_amount), 0) AS gross_sales_all_statuses,
    COALESCE(SUM(net_amount) FILTER (WHERE sale_status = 'COMPLETED'), 0) AS net_sales_completed,
    COUNT(DISTINCT source_name || '|' || source_order_id) AS total_orders_all_statuses,
    COUNT(DISTINCT source_name || '|' || source_order_id) FILTER (WHERE sale_status = 'COMPLETED') AS completed_orders,
    COUNT(DISTINCT source_name || '|' || source_order_id) FILTER (WHERE sale_status = 'RETURNED') AS returned_orders,
    COALESCE(SUM(quantity) FILTER (WHERE sale_status = 'COMPLETED'), 0) AS completed_units,
    ROUND(
        100.0 * COUNT(DISTINCT source_name || '|' || source_order_id) FILTER (WHERE sale_status = 'RETURNED')
        / NULLIF(COUNT(DISTINCT source_name || '|' || source_order_id), 0),
        2
    ) AS return_rate_pct,
    ROUND(
        SUM(net_amount) FILTER (WHERE sale_status = 'COMPLETED')
        / NULLIF(COUNT(DISTINCT source_name || '|' || source_order_id) FILTER (WHERE sale_status = 'COMPLETED'), 0),
        2
    ) AS average_order_value
FROM warehouse.fact_sales;

CREATE OR REPLACE VIEW warehouse.v_sales_monthly_kpi AS
SELECT
    DATE_TRUNC('month', d.full_date)::date AS month_start,
    COALESCE(SUM(f.gross_amount), 0) AS gross_sales_all_statuses,
    COALESCE(SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED'), 0) AS net_sales_completed,
    COUNT(DISTINCT f.source_name || '|' || f.source_order_id) AS total_orders_all_statuses,
    COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED') AS completed_orders,
    COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'RETURNED') AS returned_orders,
    ROUND(
        100.0 * COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'RETURNED')
        / NULLIF(COUNT(DISTINCT f.source_name || '|' || f.source_order_id), 0),
        2
    ) AS return_rate_pct,
    ROUND(
        SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED')
        / NULLIF(COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED'), 0),
        2
    ) AS average_order_value
FROM warehouse.fact_sales f
JOIN warehouse.dim_date d ON d.date_key = f.date_key
GROUP BY DATE_TRUNC('month', d.full_date)::date;

CREATE OR REPLACE VIEW warehouse.v_sales_channel_kpi AS
SELECT
    c.channel_code,
    c.channel_name,
    c.channel_type,
    COALESCE(SUM(f.gross_amount), 0) AS gross_sales_all_statuses,
    COALESCE(SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED'), 0) AS net_sales_completed,
    COUNT(DISTINCT f.source_name || '|' || f.source_order_id) AS total_orders_all_statuses,
    COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED') AS completed_orders,
    COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'RETURNED') AS returned_orders,
    ROUND(
        100.0 * COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'RETURNED')
        / NULLIF(COUNT(DISTINCT f.source_name || '|' || f.source_order_id), 0),
        2
    ) AS return_rate_pct,
    ROUND(
        SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED')
        / NULLIF(COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED'), 0),
        2
    ) AS average_order_value
FROM warehouse.fact_sales f
JOIN warehouse.dim_channel c ON c.channel_key = f.channel_key
GROUP BY c.channel_code, c.channel_name, c.channel_type;

CREATE OR REPLACE VIEW warehouse.v_top_product_kpi AS
SELECT
    p.sku AS product_id,
    p.product_name,
    p.brand,
    p.category,
    COALESCE(SUM(f.gross_amount), 0) AS gross_sales_all_statuses,
    COALESCE(SUM(f.net_amount) FILTER (WHERE f.sale_status = 'COMPLETED'), 0) AS net_sales_completed,
    COALESCE(SUM(f.quantity) FILTER (WHERE f.sale_status = 'COMPLETED'), 0) AS completed_units,
    COUNT(DISTINCT f.source_name || '|' || f.source_order_id) FILTER (WHERE f.sale_status = 'COMPLETED') AS completed_orders
FROM warehouse.fact_sales f
JOIN warehouse.dim_product p ON p.product_key = f.product_key
GROUP BY p.sku, p.product_name, p.brand, p.category;

CREATE OR REPLACE VIEW warehouse.v_sales_status_kpi AS
SELECT
    sale_status,
    COUNT(DISTINCT source_name || '|' || source_order_id) AS orders,
    COALESCE(SUM(quantity), 0) AS units,
    COALESCE(SUM(gross_amount), 0) AS gross_sales,
    COALESCE(SUM(net_amount), 0) AS net_sales
FROM warehouse.fact_sales
GROUP BY sale_status;

-- Quality evidence is queryable by run, source, and failed rule.
CREATE OR REPLACE VIEW audit.v_data_quality_by_rule AS
SELECT
    r.run_id,
    r.pipeline_name,
    r.started_at,
    r.status AS pipeline_status,
    q.source_name,
    q.rule_name,
    q.severity,
    SUM(q.failed_records) AS failed_records,
    MAX(q.evaluated_at) AS evaluated_at,
    q.details
FROM audit.data_quality_results q
JOIN audit.pipeline_runs r ON r.run_id = q.run_id
GROUP BY r.run_id, r.pipeline_name, r.started_at, r.status,
         q.source_name, q.rule_name, q.severity, q.details;

-- One row per run and source. Values ending in "issue_records" count findings,
-- so one source row may contribute to more than one column when it has several errors.
CREATE OR REPLACE VIEW audit.v_data_quality_report AS
WITH source_metrics AS (
    SELECT
        r.run_id,
        r.pipeline_name,
        r.started_at,
        r.status AS pipeline_status,
        metric ->> 'source_name' AS source_name,
        COALESCE((metric ->> 'source_records')::BIGINT, 0) AS source_records,
        COALESCE((metric ->> 'extracted_records')::BIGINT, 0) AS candidate_records,
        COALESCE((metric ->> 'skipped_unchanged_records')::BIGINT, 0) AS skipped_unchanged_records,
        COALESCE((metric ->> 'validated_records')::BIGINT, 0) AS valid_records,
        COALESCE((metric ->> 'rejected_records')::BIGINT, 0) AS rejected_records,
        COALESCE((metric ->> 'duplicate_records')::BIGINT, 0) AS duplicate_records
    FROM audit.pipeline_runs r
    CROSS JOIN LATERAL jsonb_array_elements(COALESCE(r.source_metrics, '[]'::jsonb)) AS metric
), quality_summary AS (
    SELECT
        q.run_id,
        q.source_name,
        COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'missing_value'), 0) AS missing_value_records,
        COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'duplicate'), 0) AS duplicate_issue_records,
        COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'invalid_quantity'), 0) AS invalid_quantity_records,
        COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'invalid_price_or_amount'), 0) AS invalid_price_or_amount_records,
        COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'invalid_date'), 0) AS invalid_date_records,
        COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'invalid_status'), 0) AS invalid_status_records,
        COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'unmapped_product'), 0) AS unmapped_product_records,
        COALESCE(SUM(q.failed_records) FILTER (WHERE q.details ->> 'category' = 'other'), 0) AS other_issue_records,
        COALESCE(SUM(q.failed_records) FILTER (WHERE q.severity = 'WARNING'), 0) AS warning_issue_records
    FROM audit.data_quality_results q
    GROUP BY q.run_id, q.source_name
)
SELECT
    m.*,
    COALESCE(q.missing_value_records, 0) AS missing_value_records,
    COALESCE(q.duplicate_issue_records, 0) AS duplicate_issue_records,
    COALESCE(q.invalid_quantity_records, 0) AS invalid_quantity_records,
    COALESCE(q.invalid_price_or_amount_records, 0) AS invalid_price_or_amount_records,
    COALESCE(q.invalid_date_records, 0) AS invalid_date_records,
    COALESCE(q.invalid_status_records, 0) AS invalid_status_records,
    COALESCE(q.unmapped_product_records, 0) AS unmapped_product_records,
    COALESCE(q.other_issue_records, 0) AS other_issue_records,
    COALESCE(q.warning_issue_records, 0) AS warning_issue_records
FROM source_metrics m
LEFT JOIN quality_summary q ON q.run_id = m.run_id AND q.source_name = m.source_name;
