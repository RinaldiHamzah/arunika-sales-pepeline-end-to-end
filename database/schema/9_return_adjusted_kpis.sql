DROP VIEW IF EXISTS warehouse.v_sales_status_kpi;
DROP VIEW IF EXISTS warehouse.v_top_product_kpi;
DROP VIEW IF EXISTS warehouse.v_sales_channel_kpi;
DROP VIEW IF EXISTS warehouse.v_sales_monthly_kpi;
DROP VIEW IF EXISTS warehouse.v_sales_kpi;
DROP VIEW IF EXISTS warehouse.v_sales_by_product;
DROP VIEW IF EXISTS warehouse.v_sales_by_channel;
DROP VIEW IF EXISTS warehouse.v_sales_by_month;
DROP VIEW IF EXISTS warehouse.v_sales_detail;

-- KPI date cohort uses order_date. Eligible sales are fulfilled sales, including
-- lines subsequently marked RETURNED; cancellations are excluded.
CREATE VIEW warehouse.v_sales_detail AS
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
    f.sale_status IN ('COMPLETED', 'RETURNED') AS is_eligible_sale,
    cu.customer_name,
    cu.city,
    pm.payment_method,
    f.quantity,
    f.unit_price,
    f.gross_amount,
    f.discount_amount,
    f.net_amount AS sales_after_discount,
    f.net_amount,
    f.loaded_at,
    f.promo_code,
    COALESCE(r.returned_units, 0) AS returned_units,
    COALESCE(r.processed_refund_amount, 0) AS processed_refund_amount
FROM warehouse.fact_sales f
JOIN warehouse.dim_date d ON d.date_key = f.date_key
JOIN warehouse.dim_product p ON p.product_key = f.product_key
JOIN warehouse.dim_channel c ON c.channel_key = f.channel_key
LEFT JOIN warehouse.dim_customer cu ON cu.customer_key = f.customer_key
LEFT JOIN warehouse.dim_payment pm ON pm.payment_key = f.payment_key
LEFT JOIN (
    SELECT source_name, source_order_id, source_line_number,
           SUM(quantity_returned) FILTER (WHERE return_status IN ('APPROVED', 'PROCESSED')) AS returned_units,
           SUM(refund_amount) FILTER (WHERE refund_status = 'PROCESSED') AS processed_refund_amount
    FROM warehouse.fact_returns
    GROUP BY source_name, source_order_id, source_line_number
) r ON r.source_name = f.source_name
   AND r.source_order_id = f.source_order_id
   AND r.source_line_number = f.source_line_number
WHERE f.is_source_active;

CREATE VIEW warehouse.v_sales_by_month AS
SELECT d.year_number, d.month_number, d.month_name, f.sale_status AS status,
       SUM(f.quantity) AS quantity_sold, COUNT(*) AS order_lines,
       SUM(f.gross_amount) AS gross_sales, SUM(f.net_amount) AS sales_after_discount,
       SUM(v.returned_units) AS returned_units,
       SUM(v.processed_refund_amount) AS processed_refund_amount,
       SUM(v.net_amount - v.processed_refund_amount) FILTER (WHERE v.is_eligible_sale) AS net_sales_after_refunds
FROM warehouse.fact_sales f
JOIN warehouse.dim_date d ON d.date_key = f.date_key
JOIN warehouse.v_sales_detail v ON v.sales_key = f.sales_key
WHERE f.is_source_active
GROUP BY d.year_number, d.month_number, d.month_name, f.sale_status;

CREATE VIEW warehouse.v_sales_by_channel AS
SELECT c.channel_code, c.channel_name, c.channel_type, f.sale_status AS status,
       COUNT(*) AS order_lines, SUM(f.quantity) AS quantity_sold,
       SUM(f.gross_amount) AS gross_sales, SUM(f.net_amount) AS sales_after_discount,
       SUM(v.returned_units) AS returned_units,
       SUM(v.processed_refund_amount) AS processed_refund_amount,
       SUM(v.net_amount - v.processed_refund_amount) FILTER (WHERE v.is_eligible_sale) AS net_sales_after_refunds
FROM warehouse.fact_sales f
JOIN warehouse.dim_channel c ON c.channel_key = f.channel_key
JOIN warehouse.v_sales_detail v ON v.sales_key = f.sales_key
WHERE f.is_source_active
GROUP BY c.channel_code, c.channel_name, c.channel_type, f.sale_status;

CREATE VIEW warehouse.v_sales_by_product AS
SELECT p.sku AS product_id, p.product_name, p.brand, p.category, f.sale_status AS status,
       COUNT(*) AS order_lines, SUM(f.quantity) AS quantity_sold,
       SUM(f.gross_amount) AS gross_sales, SUM(f.net_amount) AS sales_after_discount,
       SUM(v.returned_units) AS returned_units,
       SUM(v.processed_refund_amount) AS processed_refund_amount,
       SUM(v.net_amount - v.processed_refund_amount) FILTER (WHERE v.is_eligible_sale) AS net_sales_after_refunds
FROM warehouse.fact_sales f
JOIN warehouse.dim_product p ON p.product_key = f.product_key
JOIN warehouse.v_sales_detail v ON v.sales_key = f.sales_key
WHERE f.is_source_active
GROUP BY p.sku, p.product_name, p.brand, p.category, f.sale_status;

CREATE VIEW warehouse.v_sales_kpi AS
SELECT
    COALESCE(SUM(gross_amount), 0) AS gross_order_value_all_statuses,
    COALESCE(SUM(gross_amount) FILTER (WHERE is_eligible_sale), 0) AS gross_sales_eligible,
    COALESCE(SUM(sales_after_discount) FILTER (WHERE is_eligible_sale), 0) AS sales_after_discount_eligible,
    COALESCE(SUM(sales_after_discount - processed_refund_amount)
             FILTER (WHERE is_eligible_sale), 0) AS net_sales_after_refunds,
    COALESCE(SUM(discount_amount) FILTER (WHERE is_eligible_sale), 0) AS discounts_eligible,
    COUNT(DISTINCT source_name || '|' || order_id) AS total_orders_all_statuses,
    COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE is_eligible_sale) AS eligible_orders,
    COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE status = 'COMPLETED') AS completed_orders,
    COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE status = 'RETURNED') AS returned_status_orders,
    COALESCE(SUM(quantity) FILTER (WHERE is_eligible_sale), 0) AS eligible_units,
    COUNT(DISTINCT source_name || '|' || order_id)
        FILTER (WHERE is_eligible_sale AND returned_units > 0) AS returned_orders,
    COUNT(*) FILTER (WHERE is_eligible_sale AND returned_units > 0) AS returned_order_lines,
    COALESCE(SUM(returned_units) FILTER (WHERE is_eligible_sale), 0) AS returned_units,
    COALESCE(SUM(processed_refund_amount) FILTER (WHERE is_eligible_sale), 0) AS processed_refund_amount,
    ROUND(100.0 * COUNT(DISTINCT source_name || '|' || order_id)
          FILTER (WHERE is_eligible_sale AND returned_units > 0)
          / NULLIF(COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE is_eligible_sale), 0), 2)
        AS order_return_rate_pct,
    ROUND(100.0 * COUNT(*) FILTER (WHERE is_eligible_sale AND returned_units > 0)
          / NULLIF(COUNT(*) FILTER (WHERE is_eligible_sale), 0), 2) AS line_return_rate_pct,
    ROUND(100.0 * SUM(returned_units) FILTER (WHERE is_eligible_sale)
          / NULLIF(SUM(quantity) FILTER (WHERE is_eligible_sale), 0), 2) AS unit_return_rate_pct,
    ROUND(SUM(sales_after_discount - processed_refund_amount) FILTER (WHERE is_eligible_sale)
          / NULLIF(COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE is_eligible_sale), 0), 2)
        AS average_order_value_after_refunds
FROM warehouse.v_sales_detail;

CREATE VIEW warehouse.v_sales_monthly_kpi AS
SELECT DATE_TRUNC('month', order_date)::date AS month_start,
       COALESCE(SUM(gross_amount) FILTER (WHERE is_eligible_sale), 0) AS gross_sales_eligible,
       COALESCE(SUM(sales_after_discount) FILTER (WHERE is_eligible_sale), 0) AS sales_after_discount_eligible,
       COALESCE(SUM(sales_after_discount - processed_refund_amount)
                FILTER (WHERE is_eligible_sale), 0) AS net_sales_after_refunds,
       COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE is_eligible_sale) AS eligible_orders,
       COALESCE(SUM(quantity) FILTER (WHERE is_eligible_sale), 0) AS eligible_units,
       COUNT(DISTINCT source_name || '|' || order_id)
           FILTER (WHERE is_eligible_sale AND returned_units > 0) AS returned_orders,
       COUNT(*) FILTER (WHERE is_eligible_sale AND returned_units > 0) AS returned_order_lines,
       COALESCE(SUM(returned_units) FILTER (WHERE is_eligible_sale), 0) AS returned_units,
       COALESCE(SUM(processed_refund_amount) FILTER (WHERE is_eligible_sale), 0) AS processed_refund_amount,
       ROUND(100.0 * SUM(returned_units) FILTER (WHERE is_eligible_sale)
             / NULLIF(SUM(quantity) FILTER (WHERE is_eligible_sale), 0), 2) AS unit_return_rate_pct
FROM warehouse.v_sales_detail
GROUP BY DATE_TRUNC('month', order_date)::date;

CREATE VIEW warehouse.v_sales_channel_kpi AS
SELECT c.channel_code, c.channel_name, c.channel_type,
       COALESCE(SUM(s.gross_amount) FILTER (WHERE s.is_eligible_sale), 0) AS gross_sales_eligible,
       COALESCE(SUM(s.sales_after_discount) FILTER (WHERE s.is_eligible_sale), 0) AS sales_after_discount_eligible,
       COALESCE(SUM(s.sales_after_discount - s.processed_refund_amount)
                FILTER (WHERE s.is_eligible_sale), 0) AS net_sales_after_refunds,
       COUNT(DISTINCT s.source_name || '|' || s.order_id) FILTER (WHERE s.is_eligible_sale) AS eligible_orders,
       COALESCE(SUM(s.quantity) FILTER (WHERE s.is_eligible_sale), 0) AS eligible_units,
       COUNT(DISTINCT s.source_name || '|' || s.order_id)
           FILTER (WHERE s.is_eligible_sale AND s.returned_units > 0) AS returned_orders,
       COUNT(*) FILTER (WHERE s.is_eligible_sale AND s.returned_units > 0) AS returned_order_lines,
       COALESCE(SUM(s.returned_units) FILTER (WHERE s.is_eligible_sale), 0) AS returned_units,
       COALESCE(SUM(s.processed_refund_amount) FILTER (WHERE s.is_eligible_sale), 0) AS processed_refund_amount,
       ROUND(100.0 * SUM(s.returned_units) FILTER (WHERE s.is_eligible_sale)
             / NULLIF(SUM(s.quantity) FILTER (WHERE s.is_eligible_sale), 0), 2) AS unit_return_rate_pct
FROM warehouse.v_sales_detail s
JOIN warehouse.dim_channel c ON c.channel_name = s.channel_name
GROUP BY c.channel_code, c.channel_name, c.channel_type;

CREATE VIEW warehouse.v_top_product_kpi AS
SELECT product_id, product_name, brand, category,
       COALESCE(SUM(gross_amount) FILTER (WHERE is_eligible_sale), 0) AS gross_sales_eligible,
       COALESCE(SUM(sales_after_discount) FILTER (WHERE is_eligible_sale), 0) AS sales_after_discount_eligible,
       COALESCE(SUM(sales_after_discount - processed_refund_amount)
                FILTER (WHERE is_eligible_sale), 0) AS net_sales_after_refunds,
       COALESCE(SUM(quantity) FILTER (WHERE is_eligible_sale), 0) AS eligible_units,
       COALESCE(SUM(returned_units) FILTER (WHERE is_eligible_sale), 0) AS returned_units,
       COALESCE(SUM(processed_refund_amount) FILTER (WHERE is_eligible_sale), 0) AS processed_refund_amount,
       COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE is_eligible_sale) AS eligible_orders
FROM warehouse.v_sales_detail
GROUP BY product_id, product_name, brand, category;

CREATE VIEW warehouse.v_sales_status_kpi AS
SELECT status AS sale_status,
       COUNT(DISTINCT source_name || '|' || order_id) AS orders,
       COALESCE(SUM(quantity), 0) AS units,
       COALESCE(SUM(gross_amount), 0) AS gross_order_value,
       COALESCE(SUM(sales_after_discount), 0) AS sales_after_discount,
       COALESCE(SUM(returned_units), 0) AS returned_units,
       COALESCE(SUM(processed_refund_amount), 0) AS processed_refund_amount,
       COALESCE(SUM(sales_after_discount - processed_refund_amount)
                FILTER (WHERE is_eligible_sale), 0) AS net_sales_after_refunds
FROM warehouse.v_sales_detail
GROUP BY status;
