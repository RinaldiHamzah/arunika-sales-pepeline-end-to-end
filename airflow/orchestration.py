"""Orkestrasi harian pukul 13.00 WIB untuk pipeline gudang data e-commerce."""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.providers.standard.operators.empty import EmptyOperator
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG
from sqlalchemy import text

from pipeline.alerts import send_pipeline_report
from pipeline.database import get_engine
from pipeline.logger import get_logger
from pipeline.runner import run
from scripts.check_warehouse import validate_warehouse

LOGGER = get_logger(__name__)


def run_pipeline_task(**context):
    """Jalankan ETL dan tulis catatan operasional ringkas ke log Airflow."""
    task_instance = context["ti"]
    LOGGER.info(
        "airflow_task_started",
        extra={
            "pipeline_name": "ecommerce_sales_pipeline",
            "status": "RUNNING",
            "run_id": context.get("run_id") or task_instance.run_id,
        },
    )
    pipeline_run_id = run(orchestration_run_id=context["run_id"])
    LOGGER.info(
        "airflow_task_completed",
        extra={
            "pipeline_name": "ecommerce_sales_pipeline",
            "status": "SUCCESS",
            "run_id": str(pipeline_run_id),
        },
    )
    return str(pipeline_run_id)


def email_pipeline_report_task(**context):
    """Kirim ringkasan audit harian setelah DAG mencapai status akhir."""
    with get_engine().connect() as connection:
        report = (
            connection.execute(
                text("""
                    SELECT run_id, status, started_at, ended_at, duration_seconds,
                           extracted_records, validated_records, rejected_records,
                           duplicate_records, incremental_records, fact_inserted_records,
                           fact_skipped_records, loaded_records, error_message,
                           source_records, skipped_unchanged_records, source_metrics, report_summary,
                           outcome_message
                    FROM audit.pipeline_runs
                    WHERE pipeline_name = :pipeline_name AND orchestration_run_id = :orchestration_run_id
                    ORDER BY started_at DESC
                    LIMIT 1
                """),
                {"pipeline_name": "ecommerce_sales_pipeline", "orchestration_run_id": context["run_id"]},
            )
            .mappings()
            .one_or_none()
        )
    if report is None:
        LOGGER.warning("airflow_email_report_skipped", extra={"status": "NO_AUDIT_RUN"})
        return False
    payload = dict(report)
    # Pemuatan dapat berhasil sementara validasi gudang data gagal. Jangan laporkan
    # eksekusi DAG sebagai berhasil hanya karena audit ETL menyatakan sukses.
    validated_run = context["ti"].xcom_pull(task_ids="validate_warehouse", key="return_value")
    if str(validated_run) != str(payload["run_id"]):
        payload["status"] = "FAILED"
        payload["error_message"] = payload["error_message"] or "Warehouse validation did not complete successfully."
    sent = send_pipeline_report(payload)
    if not sent:
        # Nilai ``False`` dari PythonOperator tetap menandai task sebagai sukses.
        # Lemparkan pengecualian agar Airflow mencoba ulang notifikasi dan
        # menampilkan masalah operasional pada grid DAG.
        raise RuntimeError(
            "Laporan pipeline gagal dikirim melalui SMTP. "
            "Periksa log task email_pipeline_report untuk detailnya."
        )
    LOGGER.info(
        "airflow_email_report_completed",
        extra={
            "run_id": str(payload["run_id"]),
            "status": payload["status"],
            "loaded_records": payload["loaded_records"],
        },
    )
    return True


def validate_warehouse_for_run(**context):
    pipeline_run_id = context["ti"].xcom_pull(task_ids="load_pipeline", key="return_value")
    if not pipeline_run_id:
        raise RuntimeError("No pipeline run was produced by this DAG execution")
    validate_warehouse(run_id=pipeline_run_id)
    return pipeline_run_id


with DAG(
    dag_id="ecommerce_sales_pipeline",
    description="Validate sources, load the warehouse, and verify published facts.",
    start_date=pendulum.datetime(2026, 1, 1, tz="Asia/Jakarta"),
    schedule="0 13 * * *",
    catchup=False,
    default_args={
        "owner": "data-engineering",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
    },
    max_active_runs=1,
    tags=["ecommerce", "warehouse", "quality"],
) as dag:
    load_pipeline = PythonOperator(
        task_id="load_pipeline",
        python_callable=run_pipeline_task,
    )
    validate_warehouse_task = PythonOperator(
        task_id="validate_warehouse",
        python_callable=validate_warehouse_for_run,
    )
    email_pipeline_report = PythonOperator(
        task_id="email_pipeline_report",
        python_callable=email_pipeline_report_task,
        trigger_rule="all_done",
    )

    # Task akhir yang ketat mempertahankan status gagal dari task sebelumnya,
    # meskipun task email berhasil dengan all_done. Kegagalan email juga tetap terlihat.
    complete = EmptyOperator(task_id="complete", trigger_rule="all_success")
    load_pipeline >> validate_warehouse_task >> email_pipeline_report
    [load_pipeline, validate_warehouse_task, email_pipeline_report] >> complete
