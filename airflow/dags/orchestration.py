"""Daily orchestration for the e-commerce warehouse pipeline."""
from __future__ import annotations

from datetime import datetime, timedelta

from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from pipeline.runner import run
from scripts.check_warehouse import validate_warehouse


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
		python_callable=run,
	)
	validate_warehouse_task = PythonOperator(
		task_id="validate_warehouse",
		python_callable=validate_warehouse,
	)

	load_pipeline >> validate_warehouse_task
