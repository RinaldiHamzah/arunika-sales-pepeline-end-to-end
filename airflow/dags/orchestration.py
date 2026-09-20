"""Daily orchestration for the e-commerce warehouse pipeline."""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from pipeline.logger import get_logger
from pipeline.runner import run
from scripts.check_warehouse import validate_warehouse

LOGGER = get_logger(__name__)


def run_pipeline_task(**context):
    """Run the ETL and emit a concise operational record to Airflow logs."""
    task_instance = context["ti"]
    LOGGER.info(
        "airflow_task_started",
        extra={
            "pipeline_name": "ecommerce_sales_pipeline",
            "status": "RUNNING",
            "run_id": context.get("run_id") or task_instance.run_id,
        },
    )
    pipeline_run_id = run()
    LOGGER.info(
        "airflow_task_completed",
        extra={
            "pipeline_name": "ecommerce_sales_pipeline",
            "status": "SUCCESS",
            "run_id": str(pipeline_run_id),
        },
    )
    return str(pipeline_run_id)

with DAG(
    dag_id="ecommerce_sales_pipeline",
    description="Validate sources, load the warehouse, and verify published facts.",
    start_date=datetime(2026, 1, 1),
    schedule="@daily",
    catchup=False,
    default_args={
        "owner": "data-engineering",
        "retries": 2,
        "retry_delay": timedelta(minutes=5),
    },
    tags=["ecommerce", "warehouse", "quality"],
) as dag:
    load_pipeline = PythonOperator(
        task_id="load_pipeline",
        python_callable=run_pipeline_task,
    )
    validate_warehouse_task = PythonOperator(
        task_id="validate_warehouse",
        python_callable=validate_warehouse,
    )

    load_pipeline >> validate_warehouse_task
