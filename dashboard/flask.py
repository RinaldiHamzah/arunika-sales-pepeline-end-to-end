"""Flask dashboard for the PostgreSQL sales warehouse."""

from __future__ import annotations

import csv
import hmac
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from decimal import Decimal
from io import StringIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from zoneinfo import ZoneInfo

if __package__ is None:
    sys.path.pop(0)
    sys.path.insert(0, str(Path.cwd()))

from flask import Flask, Response, jsonify, render_template, request
from sqlalchemy import create_engine, text

from pipeline.config import settings
from pipeline.execution import PipelineBusyError, reserve_run
from pipeline.logger import get_logger
from pipeline.validation.contracts import RAW_COLUMNS

app = Flask(__name__, template_folder="templates", static_folder="static")
# The dashboard is maintained from mounted local templates.  Reload templates
# and version static files by their modification time so the UI cannot serve
# an old CSS/JS file after the source has changed.
app.config["TEMPLATES_AUTO_RELOAD"] = True
LOGGER = get_logger("dashboard")
engine = create_engine(
    settings.sqlalchemy_url,
    pool_pre_ping=True,
    pool_recycle=1800,
    pool_timeout=15,
    connect_args={
        "connect_timeout": 10,
        "options": f"-c statement_timeout=30000 -c timezone={settings.app_timezone}",
    },
)
SOURCE_DIR = Path(__file__).resolve().parents[1] / "data" / "source"
SOURCE_FILES = {
    "shopee": "shopee.csv",
    "tokopedia": "tokopedia.csv",
    "website": "website.csv",
    "offline": "offline.csv",
    "product": "product.csv",
}


@app.context_processor
def template_helpers():
    """Expose a safe cache-busting version for local dashboard assets."""

    static_root = Path(app.static_folder).resolve()

    def asset_version(filename: str) -> str:
        candidate = (static_root / filename).resolve()
        try:
            candidate.relative_to(static_root)
            return str(candidate.stat().st_mtime_ns)
        except (OSError, ValueError):
            return "1"

    return {"asset_version": asset_version}


@app.after_request
def log_request(response):
    started = getattr(request, "_arunika_started", None)
    duration_ms = round((time.perf_counter() - started) * 1000, 2) if started else None
    LOGGER.info(
        "dashboard_request",
        extra={
            "request_method": request.method,
            "request_path": request.path,
            "status_code": response.status_code,
            "duration_ms": duration_ms,
        },
    )
    return response


@app.before_request
def start_request_timer():
    request._arunika_started = time.perf_counter()


def require_admin_token():
    """Return a JSON error when a state-changing dashboard request is unauthorized."""
    configured = settings.dashboard_admin_token
    supplied = request.headers.get("X-Admin-Token", "")
    if not configured:
        return jsonify({"error": "DASHBOARD_ADMIN_TOKEN belum dikonfigurasi."}), 503
    if not hmac.compare_digest(supplied, configured):
        return jsonify({"error": "Admin token tidak valid."}), 401
    return None


def recover_stale_pipeline_runs(connection) -> int:
    """Close abandoned runs so an old RUNNING audit row cannot block the UI."""
    return connection.execute(
        text("""
        UPDATE audit.pipeline_runs
        SET status = 'FAILED',
            ended_at = CURRENT_TIMESTAMP,
            current_stage = 'failed',
            duration_seconds = EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP - started_at)),
            error_message = COALESCE(
                error_message,
                'Run ditutup otomatis karena melebihi batas waktu tanpa heartbeat.'
            )
        WHERE status = 'RUNNING'
          AND started_at < CURRENT_TIMESTAMP - (:stale_minutes * INTERVAL '1 minute')
    """),
        {"stale_minutes": settings.pipeline_stale_run_minutes},
    ).rowcount


def append_csv_batch(source_key: str, payload: bytes) -> int:
    """Validate a source CSV contract and append it to the mounted source file."""
    if source_key not in SOURCE_FILES:
        raise ValueError("Source tidak didukung.")
    try:
        decoded = payload.decode("utf-8-sig")
    except UnicodeDecodeError as error:
        raise ValueError("CSV harus menggunakan encoding UTF-8.") from error
    reader = csv.DictReader(StringIO(decoded))
    expected = list(RAW_COLUMNS[source_key])
    if reader.fieldnames != expected:
        raise ValueError(f"Header {source_key}.csv harus persis: {', '.join(expected)}")
    rows = list(reader)
    if not rows:
        raise ValueError("CSV tidak memiliki baris transaksi.")
    target = SOURCE_DIR / SOURCE_FILES[source_key]
    if not target.exists():
        raise ValueError(f"Source target tidak ditemukan: {target.name}")
    with target.open("a", newline="", encoding="utf-8") as file:
        csv.DictWriter(file, fieldnames=expected).writerows(rows)
    return len(rows)


def airflow_health() -> dict:
    """Read the Airflow health endpoint without exposing Airflow credentials."""
    try:
        with urlopen(settings.airflow_health_url, timeout=3) as response:
            return {"reachable": response.status == 200, "detail": response.read().decode("utf-8")[:500]}
    except (OSError, TimeoutError, URLError) as error:
        return {"reachable": False, "detail": str(error)}


def default_date_range() -> tuple[str, str]:
    """Return the warehouse history through today's Jakarta business date."""
    today = datetime.now(ZoneInfo(settings.app_timezone)).date()
    try:
        with engine.connect() as connection:
            first_order_date = connection.execute(
                text("SELECT MIN(order_date) FROM warehouse.v_sales_detail")
            ).scalar_one()
    except Exception:
        # The dashboard request will report the database error in its normal
        # response path. A safe fallback keeps this helper side-effect free.
        first_order_date = None
    return (first_order_date or today).isoformat(), today.isoformat()


def parse_filters():
    default_start, default_end = default_date_range()
    return (
        request.args.get("start") or default_start,
        request.args.get("end") or default_end,
        request.args.getlist("channel"),
        request.args.getlist("status"),
        request.args.getlist("category"),
        request.args.getlist("brand"),
        request.args.getlist("product"),
    )


def build_filter_clause(start, end, channels, statuses, categories, brands=None, products=None):
    """Build the bound filter shared by detail, KPI, and chart SQL queries."""
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


def query_dashboard_analytics(start, end, channels, statuses, categories, brands=None, products=None):
    """Calculate dashboard KPIs and charts in PostgreSQL for the active filters."""
    where, params = build_filter_clause(start, end, channels, statuses, categories, brands, products)
    usable_city = "LOWER(TRIM(COALESCE(city, ''))) NOT IN ('', 'nan', 'none', 'null', 'n/a', 'na')"
    source = f"FROM warehouse.v_sales_detail WHERE {where}"
    completed_source = f"{source} AND status = 'COMPLETED'"
    with engine.connect() as connection:
        metrics = (
            connection.execute(
                text(f"""
                    SELECT COALESCE(SUM(gross_amount), 0) AS gross_sales,
                           COALESCE(SUM(net_amount) FILTER (WHERE status = 'COMPLETED'), 0) AS net_sales,
                           COUNT(DISTINCT source_name || '|' || order_id)
                               FILTER (WHERE status = 'COMPLETED') AS completed_orders,
                           COALESCE(SUM(quantity) FILTER (WHERE status = 'COMPLETED'), 0) AS completed_units,
                           COUNT(DISTINCT source_name || '|' || order_id) AS total_orders,
                           COUNT(DISTINCT source_name || '|' || order_id)
                               FILTER (WHERE status = 'RETURNED') AS returned_orders,
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
                           COALESCE(SUM(net_amount) FILTER (WHERE status = 'COMPLETED'), 0) AS net,
                           COALESCE(SUM(gross_amount), 0) AS gross
                    {source}
                    GROUP BY TO_CHAR(order_date, 'YYYY-MM')
                    ORDER BY label
                """),
                params,
            )
            .mappings()
            .all(),
            "channel": connection.execute(
                text(f"""
                    SELECT channel_name AS label, COALESCE(SUM(net_amount), 0) AS value
                    {completed_source}
                    GROUP BY channel_name
                    ORDER BY value DESC, label
                """),
                params,
            )
            .mappings()
            .all(),
            "product": connection.execute(
                text(f"""
                    SELECT product_name AS label, COALESCE(SUM(quantity), 0) AS quantity,
                           COALESCE(SUM(net_amount), 0) AS net_sales
                    {completed_source}
                    GROUP BY product_name
                    ORDER BY quantity DESC, label
                    LIMIT 10
                """),
                params,
            )
            .mappings()
            .all(),
            "status": connection.execute(
                text(f"""
                    SELECT status AS label, COUNT(*) AS orders,
                           COALESCE(SUM(net_amount), 0) AS net_sales
                    {source}
                    GROUP BY status
                    ORDER BY label
                """),
                params,
            )
            .mappings()
            .all(),
            "category": connection.execute(
                text(f"""
                    SELECT COALESCE(NULLIF(TRIM(category), ''), 'Uncategorized') AS label,
                           COALESCE(SUM(net_amount), 0) AS value
                    {completed_source}
                    GROUP BY COALESCE(NULLIF(TRIM(category), ''), 'Uncategorized')
                    ORDER BY value DESC, label
                """),
                params,
            )
            .mappings()
            .all(),
            "city": connection.execute(
                text(f"""
                    SELECT city AS label, COALESCE(SUM(net_amount), 0) AS value
                    {completed_source} AND {usable_city}
                    GROUP BY city
                    ORDER BY value DESC, label
                    LIMIT 6
                """),
                params,
            )
            .mappings()
            .all(),
            "brand": connection.execute(
                text(f"""
                    SELECT COALESCE(NULLIF(TRIM(brand), ''), 'Unknown brand') AS label,
                           COALESCE(SUM(net_amount), 0) AS value
                    {completed_source}
                    GROUP BY COALESCE(NULLIF(TRIM(brand), ''), 'Unknown brand')
                    ORDER BY value DESC, label
                    LIMIT 7
                """),
                params,
            )
            .mappings()
            .all(),
            "sku": connection.execute(
                text(f"""
                    SELECT COALESCE(NULLIF(TRIM(product_id), ''), 'Unknown SKU') AS label,
                           COALESCE(SUM(net_amount), 0) AS value
                    {completed_source}
                    GROUP BY COALESCE(NULLIF(TRIM(product_id), ''), 'Unknown SKU')
                    ORDER BY value DESC, label
                    LIMIT 7
                """),
                params,
            )
            .mappings()
            .all(),
        }
    return dict(metrics), {name: serializable(rows) for name, rows in charts.items()}


def query_data(start, end, channels, statuses, categories, brands=None, products=None):
    where, params = build_filter_clause(start, end, channels, statuses, categories, brands, products)
    completed_where = " AND ".join([where, "status = 'COMPLETED'"])
    with engine.begin() as connection:
        detail = (
            connection.execute(
                text(f"""
            SELECT sales_key, source_name, order_id, order_date, product_id, product_name,
                   category, brand, channel_name, status, city, quantity, gross_amount, net_amount
            FROM warehouse.v_sales_detail
            WHERE {where}
            ORDER BY order_date DESC, sales_key DESC
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
            FROM warehouse.v_sales_detail
            ORDER BY channel_name, category, status
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
            SELECT COALESCE(100.0 * AVG((status = 'SUCCESS')::int), 0)
            FROM audit.pipeline_runs
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
        previous = None
        try:
            current_start, current_end = date.fromisoformat(start), date.fromisoformat(end)
            period_days = (current_end - current_start).days + 1
            previous_end = current_start - timedelta(days=1)
            previous_start = previous_end - timedelta(days=period_days - 1)
            previous_params = dict(params, start=previous_start.isoformat(), end=previous_end.isoformat())
            previous = (
                connection.execute(
                    text(f"""
                SELECT COALESCE(SUM(net_amount), 0) AS net_sales,
                       COALESCE(SUM(gross_amount), 0) AS gross_sales,
                       COUNT(DISTINCT source_name || '|' || order_id) AS orders
                FROM warehouse.v_sales_detail WHERE {completed_where}
            """),
                    previous_params,
                )
                .mappings()
                .one()
            )
        except (ValueError, TypeError):
            previous = {"net_sales": 0, "gross_sales": 0, "orders": 0}
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


def serializable(rows):
    result = []
    for row in rows:
        item = dict(row)
        for key, value in item.items():
            if isinstance(value, (date, Decimal)):
                item[key] = value.isoformat() if isinstance(value, date) else float(value)
        result.append(item)
    return result


def operation_runs_for_display(rows):
    """Expose processing results to the UI without snapshot-only audit metrics."""
    visible = []
    for row in serializable(rows):
        row.pop("source_records", None)
        row.pop("skipped_unchanged_records", None)
        row.pop("fact_skipped_records", None)
        row["source_metrics"] = [
            {
                key: source.get(key)
                for key in (
                    "source_name",
                    "extracted_records",
                    "validated_records",
                    "rejected_records",
                    "duplicate_records",
                )
            }
            for source in (row.get("source_metrics") or [])
        ]
        visible.append(row)
    return visible


def display_label(value, fallback: str) -> str:
    """Return a safe analytics label; never expose source null markers to users."""
    if value is None:
        return fallback
    label = str(value).strip()
    return fallback if label.casefold() in {"", "nan", "none", "null", "n/a", "na"} else label


@app.get("/")
def index():
    return render_template("dashboard.html")


@app.get("/healthz")
def healthz():
    """Liveness/readiness probe for Docker and external monitors."""
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "service": "dashboard", "database": "ok"})
    except Exception:
        return jsonify({"status": "degraded", "service": "dashboard", "database": "unavailable"}), 503


@app.post("/api/pipeline/run")
def run_pipeline():
    """Start one idempotent pipeline run from the dashboard."""
    authorization_error = require_admin_token()
    if authorization_error:
        return authorization_error
    run_id = None
    try:
        with engine.begin() as connection:
            run_id = reserve_run(connection, settings.pipeline_name)
        root = Path(__file__).resolve().parents[1]
        process = subprocess.Popen(
            [sys.executable, "-m", "pipeline.runner", "--run-id", str(run_id)],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({"status": "started", "process_id": process.pid, "run_id": str(run_id)}), 202
    except PipelineBusyError:
        return jsonify({"status": "already_running", "error": "Pipeline sedang menunggu atau berjalan."}), 409
    except Exception as error:
        if run_id:
            with engine.begin() as connection:
                connection.execute(
                    text("""
                    UPDATE audit.pipeline_runs SET status='FAILED', ended_at=CURRENT_TIMESTAMP,
                        current_stage='failed', error_message='Unable to start pipeline worker'
                    WHERE run_id=:run_id AND status='RUNNING' AND current_stage='queued'
                """),
                    {"run_id": run_id},
                )
        payload = {"status": "failed", "error": "Pipeline tidak dapat dijalankan."}
        if settings.flask_debug:
            payload["detail"] = str(error)
        return jsonify(payload), 503


@app.get("/api/pipeline/progress")
def pipeline_progress():
    """Return the active pipeline stage for the authenticated dashboard control."""
    authorization_error = require_admin_token()
    if authorization_error:
        return authorization_error
    with engine.connect() as connection:
        run = (
            connection.execute(
                text("""
                SELECT run_id, status, current_stage, current_stage_started_at,
                       started_at, ended_at, duration_seconds, error_message, outcome_message
                FROM audit.pipeline_runs
                ORDER BY (status = 'RUNNING') DESC, started_at DESC
                LIMIT 1
            """)
            )
            .mappings()
            .one_or_none()
        )
        stages = []
        if run:
            stages = (
                connection.execute(
                    text("""
                    SELECT stage_name, status, started_at, ended_at, duration_seconds,
                           records_processed, error_message
                    FROM audit.pipeline_stage_runs
                    WHERE run_id = :run_id
                    ORDER BY started_at
                """),
                    {"run_id": run["run_id"]},
                )
                .mappings()
                .all()
            )
    return jsonify({"run": serializable([run])[0] if run else None, "stages": serializable(stages)})


@app.post("/api/ingestion/upload")
def upload_source_batch():
    """Append a validated CSV transaction batch to one supported source."""
    authorization_error = require_admin_token()
    if authorization_error:
        return authorization_error
    upload = request.files.get("file")
    source_key = request.form.get("source", "")
    if upload is None or not upload.filename:
        return jsonify({"error": "Pilih file CSV untuk diunggah."}), 400
    if not upload.filename.lower().endswith(".csv"):
        return jsonify({"error": "Hanya file .csv yang didukung."}), 400
    payload = upload.read()
    if len(payload) > 10 * 1024 * 1024:
        return jsonify({"error": "Ukuran CSV maksimum adalah 10 MB."}), 413
    try:
        rows = append_csv_batch(source_key, payload)
        return jsonify(
            {
                "status": "accepted",
                "source": source_key,
                "rows_appended": rows,
                "next_step": "Jalankan pipeline untuk memvalidasi dan memuat batch ini.",
            }
        ), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@app.get("/api/admin/operations")
def operations_status():
    """Provide admin-only scheduling and pipeline execution evidence for the UI."""
    authorization_error = require_admin_token()
    if authorization_error:
        return authorization_error
    with engine.connect() as connection:
        runs = (
            connection.execute(
                text("""
                SELECT run_id, status, started_at, ended_at, duration_seconds,
                       extracted_records, validated_records, rejected_records,
                       duplicate_records, incremental_records, fact_inserted_records,
                       fact_skipped_records, loaded_records, error_message,
                       source_records, skipped_unchanged_records, source_metrics, report_summary,
                       outcome_message
                FROM audit.pipeline_runs
                ORDER BY started_at DESC
                LIMIT 10
            """)
            )
            .mappings()
            .all()
        )
        failed_runs_7d = connection.execute(
            text("""
                SELECT COUNT(*) FROM audit.pipeline_runs
                WHERE status = 'FAILED' AND started_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
            """)
        ).scalar_one()
    return jsonify(
        {
            "dag_id": "ecommerce_sales_pipeline",
            "schedule": "0 13 * * * (13:00 WIB)",
            "airflow": airflow_health(),
            "failed_runs_last_7_days": failed_runs_7d,
            "recent_runs": operation_runs_for_display(runs),
        }
    )


@app.get("/api/dashboard")
def dashboard_data():
    try:
        start, end, channels, statuses, categories, brands, products = parse_filters()
        rows, options, observability = query_data(start, end, channels, statuses, categories, brands, products)
        data = serializable(rows)
        analytics, charts = query_dashboard_analytics(start, end, channels, statuses, categories, brands, products)
        gross_sales = float(analytics["gross_sales"] or 0)
        net_sales = float(analytics["net_sales"] or 0)
        completed_count = int(analytics["completed_orders"] or 0)
        order_count = int(analytics["total_orders"] or 0)
        returned_count = int(analytics["returned_orders"] or 0)
        unresolved_city_records = int(analytics["unresolved_city_records"] or 0)
        total_records = int(analytics["total_records"] or 0)
        latest = observability["latest_run"]
        latest_dict = serializable([latest])[0] if latest else None
        latest_rejected = (latest["rejected_records"] or 0) if latest else 0
        latest_duplicate = (latest["duplicate_records"] or 0) if latest else 0
        latest_extracted = (latest["extracted_records"] or 0) if latest else 0
        latest_incremental = (latest["incremental_records"] or 0) if latest else 0
        previous = observability["previous"] or {"net_sales": 0, "gross_sales": 0, "orders": 0}
        previous_net = float(previous["net_sales"] or 0)
        net_change = ((net_sales - previous_net) / previous_net * 100) if previous_net else None
        return jsonify(
            {
                "filters": {
                    "start": start,
                    "end": end,
                    "channels": channels,
                    "statuses": statuses,
                    "categories": categories,
                    "brands": brands,
                    "products": products,
                },
                "options": {
                    "channels": sorted({row["channel_name"] for row in options}),
                    "categories": sorted({row["category"] for row in options}),
                    "statuses": sorted({row["status"] for row in options}),
                    "brands": sorted({row["brand"] for row in options}),
                    "products": sorted({row["product_id"] for row in options}),
                },
                "metrics": {
                    "net_sales": net_sales,
                    "gross_sales": gross_sales,
                    "orders": completed_count,
                    "units": float(analytics["completed_units"] or 0),
                    "completed": completed_count,
                    "return_rate": (returned_count / order_count * 100) if order_count else 0,
                    "average_order_value": (net_sales / completed_count) if completed_count else 0,
                    "net_change_percent": net_change,
                },
                "observability": {
                    "pipeline_success_rate": float(observability["success_rate"] or 0),
                    "pipeline_duration": latest_dict.get("duration_seconds") if latest_dict else None,
                    "rejected_record_rate": (latest_rejected / latest_extracted * 100) if latest_extracted else 0,
                    "duplicate_rate": (latest_duplicate / latest_extracted * 100) if latest_extracted else 0,
                    "fact_load_rate": (latest["fact_inserted_records"] / latest_incremental * 100)
                    if latest_incremental
                    else 0,
                    "latest_run": latest_dict,
                    "source_freshness": serializable(observability["freshness"]),
                    "stages": serializable(observability["stages"]),
                    "known_city_coverage_rate": (
                        (total_records - unresolved_city_records) / total_records * 100 if total_records else 0
                    ),
                    "unresolved_city_records": unresolved_city_records,
                },
                "charts": {
                    **charts,
                },
                "rows": data,
            }
        )
    except Exception as error:
        payload = {"error": "Dashboard gagal mengambil data."}
        if settings.flask_debug:
            payload["detail"] = str(error)
        return jsonify(payload), 503


@app.get("/api/dashboard/export")
def export_dashboard():
    """Export the currently filtered warehouse detail as CSV."""
    try:
        start, end, channels, statuses, categories, brands, products = parse_filters()
        rows, _, _ = query_data(start, end, channels, statuses, categories, brands, products)
        output = StringIO()
        if rows:
            headers = list(rows[0].keys())
            output.write(",".join(headers) + "\n")
            for row in rows:
                output.write(",".join('"' + str(row.get(key, "")).replace('"', '""') + '"' for key in headers) + "\n")
        return Response(
            output.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": "attachment; filename=arunika_sales_export.csv"},
        )
    except Exception:
        return jsonify({"error": "Export data gagal."}), 503


if __name__ == "__main__":
    if settings.flask_debug:
        app.run(host="127.0.0.1", port=8501, debug=True, use_reloader=False)
    else:
        from waitress import serve

        serve(app, host="0.0.0.0", port=8501, expose_tracebacks=False)
