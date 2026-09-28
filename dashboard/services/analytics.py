"""Warehouse query services used by dashboard routes."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import text

from .formatting import serializable


def default_date_range(engine, timezone: str) -> tuple[str, str]:
    """Return warehouse history through today's Jakarta business date."""
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
    """Build a bound filter shared by detail, KPI, and chart queries."""
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
    """Calculate dashboard KPIs and charts in PostgreSQL for active filters."""
    where, params = build_filter_clause(start, end, channels, statuses, categories, brands, products)
    usable_city = "LOWER(TRIM(COALESCE(city, ''))) NOT IN ('', 'nan', 'none', 'null', 'n/a', 'na')"
    source = f"FROM warehouse.v_sales_detail WHERE {where}"
    completed_source = f"{source} AND status = 'COMPLETED'"
    with engine.connect() as connection:
        metrics = connection.execute(text(f"""
            SELECT COALESCE(SUM(gross_amount), 0) AS gross_sales,
                   COALESCE(SUM(net_amount) FILTER (WHERE status = 'COMPLETED'), 0) AS net_sales,
                   COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE status = 'COMPLETED') AS completed_orders,
                   COALESCE(SUM(quantity) FILTER (WHERE status = 'COMPLETED'), 0) AS completed_units,
                   COUNT(DISTINCT source_name || '|' || order_id) AS total_orders,
                   COUNT(DISTINCT source_name || '|' || order_id) FILTER (WHERE status = 'RETURNED') AS returned_orders,
                   COUNT(*) FILTER (WHERE NOT ({usable_city})) AS unresolved_city_records,
                   COUNT(*) AS total_records
            {source}
        """), params).mappings().one()
        charts = {
            "month": connection.execute(text(f"""
                SELECT TO_CHAR(order_date, 'YYYY-MM') AS label,
                       COALESCE(SUM(net_amount) FILTER (WHERE status = 'COMPLETED'), 0) AS net,
                       COALESCE(SUM(gross_amount), 0) AS gross
                {source} GROUP BY TO_CHAR(order_date, 'YYYY-MM') ORDER BY label
            """), params).mappings().all(),
            "channel": connection.execute(text(f"""
                SELECT channel_name AS label, COALESCE(SUM(net_amount), 0) AS value
                {completed_source} GROUP BY channel_name ORDER BY value DESC, label
            """), params).mappings().all(),
            "product": connection.execute(text(f"""
                SELECT product_name AS label, COALESCE(SUM(quantity), 0) AS quantity,
                       COALESCE(SUM(net_amount), 0) AS net_sales
                {completed_source} GROUP BY product_name ORDER BY quantity DESC, label LIMIT 10
            """), params).mappings().all(),
            "status": connection.execute(text(f"""
                SELECT status AS label, COUNT(*) AS orders, COALESCE(SUM(net_amount), 0) AS net_sales
                {source} GROUP BY status ORDER BY label
            """), params).mappings().all(),
            "category": connection.execute(text(f"""
                SELECT COALESCE(NULLIF(TRIM(category), ''), 'Uncategorized') AS label,
                       COALESCE(SUM(net_amount), 0) AS value
                {completed_source}
                GROUP BY COALESCE(NULLIF(TRIM(category), ''), 'Uncategorized') ORDER BY value DESC, label
            """), params).mappings().all(),
            "city": connection.execute(text(f"""
                SELECT city AS label, COALESCE(SUM(net_amount), 0) AS value
                {completed_source} AND {usable_city} GROUP BY city ORDER BY value DESC, label LIMIT 6
            """), params).mappings().all(),
            "brand": connection.execute(text(f"""
                SELECT COALESCE(NULLIF(TRIM(brand), ''), 'Unknown brand') AS label,
                       COALESCE(SUM(net_amount), 0) AS value
                {completed_source}
                GROUP BY COALESCE(NULLIF(TRIM(brand), ''), 'Unknown brand') ORDER BY value DESC, label LIMIT 7
            """), params).mappings().all(),
            "sku": connection.execute(text(f"""
                SELECT COALESCE(NULLIF(TRIM(product_id), ''), 'Unknown SKU') AS label,
                       COALESCE(SUM(net_amount), 0) AS value
                {completed_source}
                GROUP BY COALESCE(NULLIF(TRIM(product_id), ''), 'Unknown SKU') ORDER BY value DESC, label LIMIT 7
            """), params).mappings().all(),
        }
    return dict(metrics), {name: serializable(rows) for name, rows in charts.items()}


def query_dashboard_data(engine, start, end, channels, statuses, categories, brands=None, products=None):
    """Read detail rows, filter options, and pipeline observability data."""
    where, params = build_filter_clause(start, end, channels, statuses, categories, brands, products)
    completed_where = " AND ".join([where, "status = 'COMPLETED'"])
    with engine.begin() as connection:
        detail = connection.execute(text(f"""
            SELECT sales_key, source_name, order_id, order_date, product_id, product_name,
                   category, brand, channel_name, status, city, quantity, gross_amount, net_amount
            FROM warehouse.v_sales_detail WHERE {where} ORDER BY order_date DESC, sales_key DESC
        """), params).mappings().all()
        options = connection.execute(text("""
            SELECT DISTINCT channel_name, category, status, brand, product_id
            FROM warehouse.v_sales_detail ORDER BY channel_name, category, status
        """)).mappings().all()
        latest = connection.execute(text("""
            SELECT run_id, status, started_at, ended_at, duration_seconds,
                   extracted_records, rejected_records, duplicate_records,
                   incremental_records, fact_inserted_records
            FROM audit.pipeline_runs ORDER BY started_at DESC LIMIT 1
        """)).mappings().one_or_none()
        success_rate = connection.execute(text("""
            SELECT COALESCE(100.0 * AVG((status = 'SUCCESS')::int), 0) FROM audit.pipeline_runs
        """)).scalar_one()
        freshness = connection.execute(text("""
            SELECT source_name, MAX(extracted_at) AS last_ingested_at
            FROM audit.source_ingestions GROUP BY source_name ORDER BY source_name
        """)).mappings().all()
        previous = _previous_period(connection, params, completed_where, start, end)
        stages = []
        if latest:
            stages = connection.execute(text("""
                SELECT stage_name, status, started_at, ended_at, duration_seconds, records_processed
                FROM audit.pipeline_stage_runs WHERE run_id = :run_id ORDER BY started_at
            """), {"run_id": latest["run_id"]}).mappings().all()
    return detail, options, {
        "latest_run": latest,
        "success_rate": success_rate,
        "freshness": freshness,
        "stages": stages,
        "previous": previous,
    }


def _previous_period(connection, params, completed_where, start, end):
    """Calculate the comparable preceding date range without failing the request."""
    try:
        current_start, current_end = date.fromisoformat(start), date.fromisoformat(end)
        period_days = (current_end - current_start).days + 1
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=period_days - 1)
        previous_params = dict(params, start=previous_start.isoformat(), end=previous_end.isoformat())
        return connection.execute(text(f"""
            SELECT COALESCE(SUM(net_amount), 0) AS net_sales,
                   COALESCE(SUM(gross_amount), 0) AS gross_sales,
                   COUNT(DISTINCT source_name || '|' || order_id) AS orders
            FROM warehouse.v_sales_detail WHERE {completed_where}
        """), previous_params).mappings().one()
    except (TypeError, ValueError):
        return {"net_sales": 0, "gross_sales": 0, "orders": 0}
