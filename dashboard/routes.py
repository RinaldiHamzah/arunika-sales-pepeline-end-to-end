"""HTTP routes for dashboard pages, analytics, and administration."""

from __future__ import annotations

import hmac
import subprocess
import sys
from io import StringIO
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen
from uuid import UUID

from flask import Blueprint, Response, current_app, jsonify, render_template, request
from sqlalchemy import text

from dashboard.services.analytics import (
    default_date_range,
    query_dashboard_analytics,
    query_dashboard_data,)
from dashboard.services.formatting import operation_runs_for_display, serializable
from dashboard.services.ingestion import append_csv_batch
from pipeline.config import settings
from pipeline.execution import PipelineBusyError, reserve_run

dashboard_routes = Blueprint("dashboard", __name__)


def _engine():
    return current_app.extensions["warehouse_engine"]


def _admin_error():
    configured = settings.dashboard_admin_token
    supplied = request.headers.get("X-Admin-Token", "")
    if not configured:
        return jsonify({"error": "DASHBOARD_ADMIN_TOKEN belum dikonfigurasi."}), 503
    if not hmac.compare_digest(supplied, configured):
        return jsonify({"error": "Admin token tidak valid."}), 401
    return None


def _filters():
    default_start, default_end = default_date_range(_engine(), settings.app_timezone)
    return (
        request.args.get("start") or default_start,
        request.args.get("end") or default_end,
        request.args.getlist("channel"),
        request.args.getlist("status"),
        request.args.getlist("category"),
        request.args.getlist("brand"),
        request.args.getlist("product"),
    )


def _airflow_health() -> dict:
    try:
        with urlopen(settings.airflow_health_url, timeout=3) as response:
            return {"reachable": response.status == 200, "detail": response.read().decode("utf-8")[:500]}
    except (OSError, TimeoutError, URLError) as error:
        return {"reachable": False, "detail": str(error)}


@dashboard_routes.get("/")
def index():
    return render_template("dashboard.html")


@dashboard_routes.get("/healthz")
def healthz():
    try:
        with _engine().connect() as connection:
            connection.execute(text("SELECT 1"))
        return jsonify({"status": "ok", "service": "dashboard", "database": "ok"})
    except Exception:
        return jsonify({"status": "degraded", "service": "dashboard", "database": "unavailable"}), 503


@dashboard_routes.post("/api/pipeline/run")
def run_pipeline():
    if error := _admin_error():
        return error
    run_id = None
    try:
        with _engine().begin() as connection:
            run_id = reserve_run(connection, settings.pipeline_name)
        process = subprocess.Popen(
            [sys.executable, "-m", "pipeline.runner", "--run-id", str(run_id)],
            cwd=Path(__file__).resolve().parents[1],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return jsonify({"status": "started", "process_id": process.pid, "run_id": str(run_id)}), 202
    except PipelineBusyError:
        with _engine().connect() as connection:
            active_run_id = connection.execute(text("""
                SELECT run_id FROM audit.pipeline_runs WHERE status='RUNNING'
                ORDER BY started_at DESC LIMIT 1
            """)).scalar_one_or_none()
        return jsonify({"status": "already_running", "run_id": str(active_run_id) if active_run_id else None,
                        "error": "Pipeline sedang menunggu atau berjalan."}), 409
    except Exception as error:
        if run_id:
            with _engine().begin() as connection:
                connection.execute(text("""
                    UPDATE audit.pipeline_runs SET status='FAILED', ended_at=CURRENT_TIMESTAMP,
                    current_stage='failed', error_message='Unable to start pipeline worker'
                    WHERE run_id=:run_id AND status='RUNNING' AND current_stage='queued'
                """), {"run_id": run_id})
        payload = {"status": "failed", "error": "Pipeline tidak dapat dijalankan."}
        if settings.flask_debug:
            payload["detail"] = str(error)
        return jsonify(payload), 503


@dashboard_routes.get("/api/pipeline/progress")
def pipeline_progress():
    if error := _admin_error():
        return error
    requested_run_id = request.args.get("run_id")
    if requested_run_id:
        try:
            requested_run_id = UUID(requested_run_id)
        except ValueError:
            return jsonify({"error": "ID run tidak valid."}), 400
    with _engine().connect() as connection:
        query = text("""
            SELECT run_id, status, current_stage, current_stage_started_at, started_at, ended_at,
                   duration_seconds, error_message, outcome_message
            FROM audit.pipeline_runs WHERE run_id = :run_id
        """) if requested_run_id else text("""
            SELECT run_id, status, current_stage, current_stage_started_at, started_at, ended_at,
                   duration_seconds, error_message, outcome_message
            FROM audit.pipeline_runs ORDER BY (status = 'RUNNING') DESC, started_at DESC LIMIT 1
        """)
        statement = connection.execute(query, {"run_id": requested_run_id}) if requested_run_id else connection.execute(query)
        run = statement.mappings().one_or_none()
        stages = connection.execute(text("""
            SELECT stage_name, status, started_at, ended_at, duration_seconds, records_processed, error_message
            FROM audit.pipeline_stage_runs WHERE run_id = :run_id ORDER BY started_at
        """), {"run_id": run["run_id"]}).mappings().all() if run else []
    return jsonify({"run": serializable([run])[0] if run else None, "stages": serializable(stages)})


@dashboard_routes.post("/api/ingestion/upload")
def upload_source_batch():
    if error := _admin_error():
        return error
    upload, source_key = request.files.get("file"), request.form.get("source", "")
    if upload is None or not upload.filename:
        return jsonify({"error": "Pilih file CSV untuk diunggah."}), 400
    if not upload.filename.lower().endswith(".csv"):
        return jsonify({"error": "Hanya file .csv yang didukung."}), 400
    payload = upload.read()
    if len(payload) > 10 * 1024 * 1024:
        return jsonify({"error": "Ukuran CSV maksimum adalah 10 MB."}), 413
    try:
        rows = append_csv_batch(source_key, payload)
        return jsonify({"status": "accepted", "source": source_key, "rows_appended": rows,
                        "next_step": "Jalankan pipeline untuk memvalidasi dan memuat batch ini."}), 201
    except ValueError as error:
        return jsonify({"error": str(error)}), 400


@dashboard_routes.get("/api/admin/operations")
def operations_status():
    if error := _admin_error():
        return error
    with _engine().connect() as connection:
        runs = connection.execute(text("""
            SELECT run_id, status, started_at, ended_at, duration_seconds, extracted_records,
                   validated_records, rejected_records, duplicate_records, incremental_records,
                   fact_inserted_records, fact_skipped_records, loaded_records, error_message,
                   source_records, skipped_unchanged_records, source_metrics, report_summary, outcome_message
            FROM audit.pipeline_runs ORDER BY started_at DESC LIMIT 10
        """)).mappings().all()
        failed_runs_7d = connection.execute(text("""
            SELECT COUNT(*) FROM audit.pipeline_runs
            WHERE status = 'FAILED' AND started_at >= CURRENT_TIMESTAMP - INTERVAL '7 days'
        """)).scalar_one()
    return jsonify({"dag_id": "ecommerce_sales_pipeline", "schedule": "0 13 * * * (13:00 WIB)",
                    "airflow": _airflow_health(), "failed_runs_last_7_days": failed_runs_7d,
                    "recent_runs": operation_runs_for_display(runs)})


@dashboard_routes.get("/api/dashboard")
def dashboard_data():
    try:
        start, end, channels, statuses, categories, brands, products = _filters()
        rows, options, observability = query_dashboard_data(
            _engine(), start, end, channels, statuses, categories, brands, products
        )
        analytics, charts = query_dashboard_analytics(
            _engine(), start, end, channels, statuses, categories, brands, products
        )
        gross_sales, net_sales = float(analytics["gross_sales"] or 0), float(analytics["net_sales"] or 0)
        completed_count, order_count = int(analytics["completed_orders"] or 0), int(analytics["total_orders"] or 0)
        returned_count, total_records = int(analytics["returned_orders"] or 0), int(analytics["total_records"] or 0)
        unresolved_city_records = int(analytics["unresolved_city_records"] or 0)
        latest = observability["latest_run"]
        latest_dict = serializable([latest])[0] if latest else None
        latest_extracted = (latest["extracted_records"] or 0) if latest else 0
        latest_rejected = (latest["rejected_records"] or 0) if latest else 0
        latest_duplicate = (latest["duplicate_records"] or 0) if latest else 0
        latest_incremental = (latest["incremental_records"] or 0) if latest else 0
        previous_net = float((observability["previous"] or {"net_sales": 0})["net_sales"] or 0)
        return jsonify({
            "filters": {"start": start, "end": end, "channels": channels, "statuses": statuses,
                        "categories": categories, "brands": brands, "products": products},
            "options": {key: sorted({row[column] for row in options}) for key, column in (
                ("channels", "channel_name"), ("categories", "category"), ("statuses", "status"),
                ("brands", "brand"), ("products", "product_id"))},
            "metrics": {"net_sales": net_sales, "gross_sales": gross_sales, "orders": completed_count,
                        "units": float(analytics["completed_units"] or 0), "completed": completed_count,
                        "return_rate": (returned_count / order_count * 100) if order_count else 0,
                        "average_order_value": (net_sales / completed_count) if completed_count else 0,
                        "net_change_percent": ((net_sales - previous_net) / previous_net * 100) if previous_net else None},
            "observability": {"pipeline_success_rate": float(observability["success_rate"] or 0),
                "pipeline_duration": latest_dict.get("duration_seconds") if latest_dict else None,
                "rejected_record_rate": (latest_rejected / latest_extracted * 100) if latest_extracted else 0,
                "duplicate_rate": (latest_duplicate / latest_extracted * 100) if latest_extracted else 0,
                "fact_load_rate": (latest["fact_inserted_records"] / latest_incremental * 100) if latest_incremental else 0,
                "latest_run": latest_dict, "source_freshness": serializable(observability["freshness"]),
                "stages": serializable(observability["stages"]),
                "known_city_coverage_rate": ((total_records - unresolved_city_records) / total_records * 100) if total_records else 0,
                "unresolved_city_records": unresolved_city_records},
            "charts": charts, "rows": serializable(rows),
        })
    except Exception as error:
        payload = {"error": "Dashboard gagal mengambil data."}
        if settings.flask_debug:
            payload["detail"] = str(error)
        return jsonify(payload), 503


@dashboard_routes.get("/api/dashboard/export")
def export_dashboard():
    try:
        start, end, channels, statuses, categories, brands, products = _filters()
        rows, _, _ = query_dashboard_data(_engine(), start, end, channels, statuses, categories, brands, products)
        output = StringIO()
        if rows:
            headers = list(rows[0].keys())
            output.write(",".join(headers) + "\n")
            for row in rows:
                output.write(",".join('"' + str(row.get(key, "")).replace('"', '""') + '"' for key in headers) + "\n")
        return Response(output.getvalue(), mimetype="text/csv",
                        headers={"Content-Disposition": "attachment; filename=arunika_sales_export.csv"})
    except Exception:
        return jsonify({"error": "Export data gagal."}), 503
