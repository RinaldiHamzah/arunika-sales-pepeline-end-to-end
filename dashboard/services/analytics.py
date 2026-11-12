"""Kueri gudang data untuk dashboard."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .formatting import serializable


def default_date_range(engine, timezone: str) -> tuple[str, str]:
    """Ambil riwayat gudang data hingga tanggal bisnis hari ini di Jakarta."""
    today = datetime.now(ZoneInfo(timezone)).date()
    try:
        with engine.connect() as connection:
            first_order_date = connection.execute(
                text("SELECT MIN(order_date) FROM warehouse.v_sales_detail")
            ).scalar_one()
    except Exception:
        first_order_date = None
    return (first_order_date or today).isoformat(), today.isoformat()


def build_filter_clause(start, end, channels, statuses, categories, brands=None, products=None):
    """Susun filter terikat yang digunakan bersama oleh kueri rincian, KPI, dan grafik."""
    conditions = ["order_date BETWEEN :start AND :end"]
    params = {"start": start, "end": end}
    for name, values in (
        ("channel_name", channels),
        ("status", statuses),
        ("category", categories),
        ("brand", brands or []),
        ("product_id", products or []),
    ):
        if values:
            keys = []
            for index, value in enumerate(values):
                key = f"{name}_{index}"
                keys.append(f":{key}")
                params[key] = value
            conditions.append(f"{name} IN ({', '.join(keys)})")
    return " AND ".join(conditions), params


def query_dashboard_analytics(engine, start, end, channels, statuses, categories, brands=None, products=None):
    """Hitung KPI dan data grafik dashboard di PostgreSQL sesuai filter aktif."""
    where, params = build_filter_clause(start, end, channels, statuses, categories, brands, products)
    usable_city = "LOWER(TRIM(COALESCE(city, ''))) NOT IN ('', 'nan', 'none', 'null', 'n/a', 'na')"
    source = f"FROM warehouse.v_sales_detail WHERE {where}"
    eligible_source = f"{source} AND is_eligible_sale"
    with engine.connect() as connection:
        metrics = (
            connection.execute(
                text(f"""
            SELECT COALESCE(SUM(gross_amount), 0) AS gross_order_value_all_statuses,
                   COALESCE(SUM(gross_amount) FILTER (WHERE is_eligible_sale), 0) AS gross_sales,
                   COALESCE(SUM(net_amount) FILTER (WHERE is_eligible_sale), 0) AS sales_after_discount,
                   COALESCE(SUM(net_amount - processed_refund_amount)
                       FILTER (WHERE is_eligible_sale), 0) AS net_sales,
                   COALESCE(SUM(discount_amount) FILTER (WHERE is_eligible_sale), 0) AS discount_total,
                   COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE is_eligible_sale) AS eligible_orders,
                   COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE status = 'COMPLETED') AS completed_orders,
                   COALESCE(SUM(quantity) FILTER (WHERE is_eligible_sale), 0) AS eligible_units,
                   COUNT(DISTINCT source_name || '|' || order_id) AS total_orders,
                   COUNT(DISTINCT source_name || '|' || order_id)
                       FILTER (WHERE is_eligible_sale AND returned_units > 0) AS returned_orders,
                   COUNT(*) FILTER (WHERE is_eligible_sale AND returned_units > 0) AS returned_order_lines,
                   COALESCE(SUM(returned_units) FILTER (WHERE is_eligible_sale), 0) AS returned_units,
                   COALESCE(SUM(processed_refund_amount) FILTER (WHERE is_eligible_sale), 0)
                       AS processed_refund_amount,
                   COALESCE(ROUND(100.0 * COUNT(DISTINCT source_name || '|' || order_id)
                       FILTER (WHERE is_eligible_sale AND returned_units > 0)
                       / NULLIF(COUNT(DISTINCT source_name || '|' || order_id)
                           FILTER (WHERE is_eligible_sale), 0), 2), 0) AS order_return_rate,
                   COALESCE(ROUND(100.0 * COUNT(*) FILTER (WHERE is_eligible_sale AND returned_units > 0)
                       / NULLIF(COUNT(*) FILTER (WHERE is_eligible_sale), 0), 2), 0) AS line_return_rate,
                   COALESCE(ROUND(100.0 * SUM(returned_units) FILTER (WHERE is_eligible_sale)
                       / NULLIF(SUM(quantity) FILTER (WHERE is_eligible_sale), 0), 2), 0) AS return_rate,
                   COUNT(*) FILTER (WHERE NOT ({usable_city})) AS unresolved_city_records,
                   COUNT(*) AS total_records
            {source}
        """),
                params,
            )
            .mappings()
            .one()
        )
        charts = {
            "month": connection.execute(
                text(f"""
                SELECT TO_CHAR(order_date, 'YYYY-MM') AS label,
                       COALESCE(SUM(net_amount - processed_refund_amount)
                           FILTER (WHERE is_eligible_sale), 0) AS net,
                       COALESCE(SUM(gross_amount) FILTER (WHERE is_eligible_sale), 0) AS gross
                {source} GROUP BY TO_CHAR(order_date, 'YYYY-MM') ORDER BY label
            """),
                params,
            )
            .mappings()
            .all(),
            "channel": connection.execute(
                text(f"""
                SELECT channel_name AS label, COALESCE(SUM(net_amount - processed_refund_amount), 0) AS value
                {eligible_source} GROUP BY channel_name ORDER BY value DESC, label
            """),
                params,
            )
            .mappings()
            .all(),
            "product": connection.execute(
                text(f"""
                SELECT product_name AS label, COALESCE(SUM(quantity), 0) AS quantity,
                       COALESCE(SUM(net_amount - processed_refund_amount), 0) AS net_sales
                {eligible_source} GROUP BY product_name ORDER BY quantity DESC, label LIMIT 10
            """),
                params,
            )
            .mappings()
            .all(),
            "status": connection.execute(
                text(f"""
                SELECT status AS label, COUNT(*) AS orders,
                       COALESCE(SUM(net_amount - processed_refund_amount)
                           FILTER (WHERE is_eligible_sale), 0) AS net_sales
                {source} GROUP BY status ORDER BY label
            """),
                params,
            )
            .mappings()
            .all(),
            "category": connection.execute(
                text(f"""
                SELECT COALESCE(NULLIF(TRIM(category), ''), 'Uncategorized') AS label,
                       COALESCE(SUM(net_amount - processed_refund_amount), 0) AS value
                {eligible_source}
                GROUP BY COALESCE(NULLIF(TRIM(category), ''), 'Uncategorized') ORDER BY value DESC, label
            """),
                params,
            )
            .mappings()
            .all(),
            "city": connection.execute(
                text(f"""
                SELECT city AS label, COALESCE(SUM(net_amount - processed_refund_amount), 0) AS value
                {eligible_source} AND {usable_city} GROUP BY city ORDER BY value DESC, label LIMIT 6
            """),
                params,
            )
            .mappings()
            .all(),
            "brand": connection.execute(
                text(f"""
                SELECT COALESCE(NULLIF(TRIM(brand), ''), 'Unknown brand') AS label,
                       COALESCE(SUM(net_amount - processed_refund_amount), 0) AS value
                {eligible_source}
                GROUP BY COALESCE(NULLIF(TRIM(brand), ''), 'Unknown brand') ORDER BY value DESC, label LIMIT 7
            """),
                params,
            )
            .mappings()
            .all(),
            "sku": connection.execute(
                text(f"""
                SELECT COALESCE(NULLIF(TRIM(product_id), ''), 'Unknown SKU') AS label,
                       COALESCE(SUM(net_amount - processed_refund_amount), 0) AS value
                {eligible_source}
                GROUP BY COALESCE(NULLIF(TRIM(product_id), ''), 'Unknown SKU') ORDER BY value DESC, label LIMIT 7
            """),
                params,
            )
            .mappings()
            .all(),
            "promo": connection.execute(
                text(f"""
                SELECT promo_code AS label,
                       COALESCE(SUM(discount_amount), 0) AS value,
                       COUNT(DISTINCT source_name || '|' || order_id) AS orders
                {eligible_source}
                AND promo_code IS NOT NULL
                AND LOWER(TRIM(promo_code)) NOT IN ('', 'nan', 'none', 'null', 'n/a', 'na')
                GROUP BY promo_code ORDER BY value DESC, label LIMIT 10
            """),
                params,
            )
            .mappings()
            .all(),
        }
    return dict(metrics), {name: serializable(rows) for name, rows in charts.items()}


def query_return_analytics(engine, start, end, channels, statuses, categories, brands=None, products=None):
    """Ambil ringkasan operasional dan event retur menurut tanggal retur."""
    conditions = ["r.return_date BETWEEN :start AND :end"]
    params = {"start": start, "end": end}
    for name, column, values in (
        ("channel", "c.channel_name", channels),
        ("sale_status", "s.sale_status", statuses),
        ("category", "p.category", categories),
        ("brand", "p.brand", brands or []),
        ("product", "p.sku", products or []),
    ):
        if values:
            placeholders = []
            for index, value in enumerate(values):
                key = f"return_{name}_{index}"
                placeholders.append(f":{key}")
                params[key] = value
            conditions.append(f"{column} IN ({', '.join(placeholders)})")
    where = " AND ".join(conditions)
    source = """
        FROM warehouse.fact_returns r
        JOIN warehouse.fact_sales s
          ON s.source_name = r.source_name
         AND s.source_order_id = r.source_order_id
         AND s.source_line_number = r.source_line_number
        JOIN warehouse.dim_channel c ON c.channel_key = s.channel_key
        JOIN warehouse.dim_product p ON p.product_key = s.product_key
    """
    with engine.connect() as connection:
        result = {
            "by_status": connection.execute(text(f"""
                SELECT r.return_status AS label, COUNT(*) AS events,
                       COALESCE(SUM(r.quantity_returned), 0) AS units,
                       COUNT(*) FILTER (WHERE r.refund_status = 'PROCESSED') AS refunded_events,
                       COALESCE(SUM(r.refund_amount) FILTER (WHERE r.refund_status = 'PROCESSED'), 0)
                           AS processed_refund_amount
                {source} WHERE {where}
                GROUP BY r.return_status
                ORDER BY CASE r.return_status
                    WHEN 'PENDING' THEN 1 WHEN 'APPROVED' THEN 2
                    WHEN 'REJECTED' THEN 3 WHEN 'PROCESSED' THEN 4 ELSE 5 END
            """), params).mappings().all(),
            "by_refund_status": connection.execute(text(f"""
                SELECT r.refund_status AS label, COUNT(*) AS events,
                       COALESCE(SUM(r.refund_amount) FILTER (WHERE r.refund_status = 'PROCESSED'), 0)
                           AS processed_refund_amount
                {source} WHERE {where}
                GROUP BY r.refund_status
                ORDER BY CASE r.refund_status
                    WHEN 'PENDING' THEN 1 WHEN 'PROCESSED' THEN 2
                    WHEN 'FAILED' THEN 3 WHEN 'NOT_APPLICABLE' THEN 4 ELSE 5 END
            """), params).mappings().all(),
            "by_channel": connection.execute(text(f"""
                SELECT c.channel_name AS label, COUNT(*) AS events,
                       COALESCE(SUM(r.quantity_returned), 0) AS units,
                       COUNT(*) FILTER (WHERE r.return_status = 'PENDING') AS pending_events,
                       COUNT(*) FILTER (WHERE r.return_status = 'REJECTED') AS rejected_events,
                       COALESCE(SUM(r.refund_amount) FILTER (WHERE r.refund_status = 'PROCESSED'), 0)
                           AS processed_refund_amount
                {source} WHERE {where}
                GROUP BY c.channel_name ORDER BY events DESC, label
            """), params).mappings().all(),
            "by_reason": connection.execute(text(f"""
                SELECT r.return_reason AS label, COUNT(*) AS events,
                       COALESCE(SUM(r.quantity_returned), 0) AS units,
                       COALESCE(SUM(r.refund_amount) FILTER (WHERE r.refund_status = 'PROCESSED'), 0)
                           AS processed_refund_amount
                {source} WHERE {where}
                GROUP BY r.return_reason ORDER BY events DESC, label LIMIT 10
            """), params).mappings().all(),
            "monthly": connection.execute(text(f"""
                SELECT TO_CHAR(r.return_date, 'YYYY-MM') AS label, COUNT(*) AS events,
                       COALESCE(SUM(r.quantity_returned), 0) AS units,
                       COALESCE(SUM(r.refund_amount) FILTER (WHERE r.refund_status = 'PROCESSED'), 0)
                           AS processed_refund_amount
                {source} WHERE {where}
                GROUP BY DATE_TRUNC('month', r.return_date), TO_CHAR(r.return_date, 'YYYY-MM')
                ORDER BY DATE_TRUNC('month', r.return_date)
            """), params).mappings().all(),
            "rows": connection.execute(text(f"""
                SELECT r.return_date, r.return_id, r.return_line_number,
                       c.channel_name, r.source_order_id AS order_id, r.source_line_number,
                       p.sku AS product_id, p.product_name, r.return_status,
                       r.return_reason, r.quantity_returned, r.refund_status, r.refund_amount
                {source} WHERE {where}
                ORDER BY r.return_date DESC, r.return_id, r.return_line_number
            """), params).mappings().all(),
        }
    return {name: serializable(rows) for name, rows in result.items()}


def query_dashboard_data(engine, start, end, channels, statuses, categories, brands=None, products=None):
    """Ambil baris rincian, pilihan filter, dan data pemantauan pipeline."""
    where, params = build_filter_clause(start, end, channels, statuses, categories, brands, products)
    eligible_where = " AND ".join([where, "is_eligible_sale"])
    with engine.begin() as connection:
        detail = (
            connection.execute(
                text(f"""
            SELECT sales_key, source_name, order_id, order_date, product_id, product_name,
                   category, brand, channel_name, status, city, quantity, gross_amount,
                   discount_amount, net_amount, returned_units, processed_refund_amount, promo_code
            FROM warehouse.v_sales_detail WHERE {where} ORDER BY order_date DESC, sales_key DESC
        """),
                params,
            )
            .mappings()
            .all()
        )
        options = (
            connection.execute(
                text("""
            SELECT DISTINCT channel_name, category, status, brand, product_id
            FROM warehouse.v_sales_detail ORDER BY channel_name, category, status
        """)
            )
            .mappings()
            .all()
        )
        latest = (
            connection.execute(
                text("""
            SELECT run_id, status, started_at, ended_at, duration_seconds,
                   extracted_records, rejected_records, duplicate_records,
                   incremental_records, fact_inserted_records
            FROM audit.pipeline_runs ORDER BY started_at DESC LIMIT 1
        """)
            )
            .mappings()
            .one_or_none()
        )
        success_rate = connection.execute(
            text("""
            SELECT COALESCE(100.0 * AVG((status = 'SUCCESS')::int), 0) FROM audit.pipeline_runs
        """)
        ).scalar_one()
        freshness = (
            connection.execute(
                text("""
            SELECT source_name, MAX(extracted_at) AS last_ingested_at
            FROM audit.source_ingestions GROUP BY source_name ORDER BY source_name
        """)
            )
            .mappings()
            .all()
        )
        previous = _previous_period(connection, params, eligible_where, start, end)
        stages = []
        if latest:
            stages = (
                connection.execute(
                    text("""
                SELECT stage_name, status, started_at, ended_at, duration_seconds, records_processed
                FROM audit.pipeline_stage_runs WHERE run_id = :run_id ORDER BY started_at
            """),
                    {"run_id": latest["run_id"]},
                )
                .mappings()
                .all()
            )
    return (
        detail,
        options,
        {
            "latest_run": latest,
            "success_rate": success_rate,
            "freshness": freshness,
            "stages": stages,
            "previous": previous,
        },
    )


def _previous_period(connection, params, eligible_where, start, end):
    """Hitung rentang tanggal sebelumnya yang sebanding tanpa menggagalkan permintaan."""
    try:
        current_start, current_end = date.fromisoformat(start), date.fromisoformat(end)
        period_days = (current_end - current_start).days + 1
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=period_days - 1)
        previous_params = dict(params, start=previous_start.isoformat(), end=previous_end.isoformat())
        return (
            connection.execute(
                text(f"""
            SELECT COALESCE(SUM(net_amount - processed_refund_amount), 0) AS net_sales,
                   COALESCE(SUM(gross_amount), 0) AS gross_sales,
                   COUNT(DISTINCT source_name || '|' || order_id) AS orders
            FROM warehouse.v_sales_detail WHERE {eligible_where}
        """),
                previous_params,
            )
            .mappings()
            .one()
        )
    except (TypeError, ValueError):
        return {"net_sales": 0, "gross_sales": 0, "orders": 0}
