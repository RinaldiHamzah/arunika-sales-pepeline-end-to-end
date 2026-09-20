"""Run extraction and raw ingestion: python -m pipeline.runner."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from time import perf_counter
from zoneinfo import ZoneInfo

from sqlalchemy import text

from pipeline.alerts import notify_pipeline_failure
from pipeline.config import settings
from pipeline.database import get_engine
from pipeline.extract.sources import extract_all
from pipeline.load.audit_loader import load_quality_audit, load_stage_runs, update_watermarks
from pipeline.load.dimension_loader import load_dimensions
from pipeline.load.fact_loader import load_facts
from pipeline.load.raw_loader import load_raw
from pipeline.load.staging_loader import load_staging
from pipeline.logger import get_logger
from pipeline.transform.standardize import clean_results_to_staging, filter_incremental_results
from pipeline.validation.data_quality import run_quality

# Keep a stable logger name when this module is executed both as an import and
# via ``python -m pipeline.runner``. The latter sets ``__name__`` to
# ``__main__``; a stable name ensures the event is routed to pipeline.log.
LOGGER = get_logger("pipeline.runner")
SOURCE_DIR = Path(__file__).resolve().parents[1] / "data" / "source"
APP_TIMEZONE = ZoneInfo(settings.app_timezone)


def run(source_dir: Path | None = None):
    started = perf_counter()
    run_started_at = datetime.now(APP_TIMEZONE)
    stages = []
    source_dir = Path(source_dir) if source_dir else SOURCE_DIR
    engine = get_engine()
    with engine.begin() as connection:
        run_id = connection.execute(
            text("""
            INSERT INTO audit.pipeline_runs (pipeline_name, status, current_stage, current_stage_started_at)
            VALUES (:pipeline_name, 'RUNNING', 'starting', CURRENT_TIMESTAMP)
            RETURNING run_id
        """),
            {"pipeline_name": settings.pipeline_name},
        ).scalar_one()

    def mark_current_stage(name: str) -> None:
        """Persist stage entry immediately so the UI can report live progress."""
        with engine.begin() as connection:
            connection.execute(
                text("""
                UPDATE audit.pipeline_runs
                SET current_stage = :stage_name, current_stage_started_at = CURRENT_TIMESTAMP
                WHERE run_id = :run_id
            """),
                {"run_id": run_id, "stage_name": name},
            )

    def stage(name, operation):
        stage_started = datetime.now(APP_TIMEZONE)
        tick = perf_counter()
        mark_current_stage(name)
        try:
            result = operation()
        except Exception as error:
            stages.append(
                {
                    "stage_name": name,
                    "status": "FAILED",
                    "started_at": stage_started,
                    "ended_at": datetime.now(APP_TIMEZONE),
                    "duration_seconds": round(perf_counter() - tick, 3),
                    "records_processed": 0,
                    "error_message": str(error),
                }
            )
            raise
        stages.append(
            {
                "stage_name": name,
                "status": "SUCCESS",
                "started_at": stage_started,
                "ended_at": datetime.now(APP_TIMEZONE),
                "duration_seconds": round(perf_counter() - tick, 3),
                "records_processed": 0,
                "error_message": None,
            }
        )
        return result

    sources = stage("extract", lambda: extract_all(source_dir))
    stages[-1]["records_processed"] = sum(len(source.frame) for source in sources)
    extracted_count = sum(len(source.frame) for source in sources if source.source_name != "PRODUCT_MASTER")
    with engine.begin() as connection:
        connection.execute(
            text("""
            UPDATE audit.pipeline_runs
            SET extracted_records = :extracted_records
            WHERE run_id = :run_id
        """),
            {"run_id": run_id, "extracted_records": extracted_count},
        )

    try:
        quality_results = stage("validate", lambda: run_quality(source_dir))
        stages[-1]["records_processed"] = sum(len(result.clean) for result in quality_results.values())
        with engine.begin() as connection:
            existing_keys = {
                (row["source_name"], row["source_order_id"], row["source_line_number"]): row["source_record_hash"]
                for row in connection.execute(
                    text("""
                SELECT source_name, source_order_id, source_line_number, source_record_hash
                FROM warehouse.fact_sales
            """)
                ).mappings()
            }
        incremental_results = stage(
            "incremental_filter", lambda: filter_incremental_results(quality_results, existing_keys)
        )
        staging_rows = stage("transform", lambda: clean_results_to_staging(incremental_results))
        stages[-1]["records_processed"] = len(staging_rows)
        valid_count = sum(
            result.summary["valid_records"]
            for result in quality_results.values()
            if result.summary["source"] != "product"
        )
        duplicate_count = sum(
            result.summary["duplicate_records"]
            for result in quality_results.values()
            if result.summary["source"] != "product"
        )
        invalid_count = sum(
            result.summary["invalid_records"]
            for result in quality_results.values()
            if result.summary["source"] != "product"
        )
        with engine.begin() as connection:
            loaded_count = stage("raw_load", lambda: sum(load_raw(connection, run_id, source) for source in sources))
            stages[-1]["records_processed"] = loaded_count
            staged_count = stage("staging_load", lambda: load_staging(connection, run_id, staging_rows))
            stages[-1]["records_processed"] = staged_count
            dimension_counts = stage(
                "dimension_load", lambda: load_dimensions(connection, quality_results["product"].clean, staging_rows)
            )
            stages[-1]["records_processed"] = sum(dimension_counts.values())
            fact_before = connection.execute(text("SELECT COUNT(*) FROM warehouse.fact_sales")).scalar_one()
            fact_count = stage("fact_load", lambda: load_facts(connection, run_id))
            stages[-1]["records_processed"] = fact_count
            fact_after = connection.execute(text("SELECT COUNT(*) FROM warehouse.fact_sales")).scalar_one()
            fact_inserted_count = max(int(fact_after) - int(fact_before), 0)
            incremental_count = len(staging_rows)
            fact_skipped_count = max(valid_count - incremental_count, 0)
            load_quality_audit(connection, run_id, quality_results)
            update_watermarks(connection, run_id, quality_results)
            load_stage_runs(connection, run_id, stages)
            connection.execute(
                text("""
                UPDATE audit.pipeline_runs
                SET status = 'SUCCESS', ended_at = CURRENT_TIMESTAMP,
                    current_stage = 'completed',
                    valid_records = :valid_records, duplicate_records = :duplicate_records,
                    invalid_records = :invalid_records, loaded_records = :loaded_records,
                    validated_records = :validated_records, rejected_records = :rejected_records,
                    incremental_records = :incremental_records, staged_records = :staged_records,
                    dimension_records = :dimension_records,
                    fact_inserted_records = :fact_inserted_records,
                    fact_skipped_records = :fact_skipped_records,
                    duration_seconds = :duration_seconds
                WHERE run_id = :run_id
            """),
                {
                    "run_id": run_id,
                    "valid_records": valid_count,
                    "duplicate_records": duplicate_count,
                    "invalid_records": invalid_count,
                    "loaded_records": fact_inserted_count,
                    "validated_records": valid_count,
                    "rejected_records": invalid_count,
                    "incremental_records": incremental_count,
                    "staged_records": staged_count,
                    "dimension_records": sum(dimension_counts.values()),
                    "fact_inserted_records": fact_inserted_count,
                    "fact_skipped_records": fact_skipped_count,
                    "duration_seconds": round(perf_counter() - started, 3),
                },
            )
        run_ended_at = datetime.now(APP_TIMEZONE)
        LOGGER.info(
            "pipeline_run_completed",
            extra={
                "run_id": str(run_id),
                "pipeline_name": settings.pipeline_name,
                "status": "SUCCESS",
                "start_time": run_started_at.isoformat(),
                "end_time": run_ended_at.isoformat(),
                "extracted_records": extracted_count,
                "valid_records": valid_count,
                "duplicate_records": duplicate_count,
                "invalid_records": invalid_count,
                "loaded_records": fact_inserted_count,
                "validated_records": valid_count,
                "rejected_records": invalid_count,
                "incremental_records": incremental_count,
                "staged_records": staged_count,
                "dimension_records": sum(dimension_counts.values()),
                "fact_inserted_records": fact_inserted_count,
                "fact_skipped_records": fact_skipped_count,
                "duration_seconds": round(perf_counter() - started, 3),
                "error_message": None,
            },
        )
        return run_id
    except Exception as error:
        if run_id is not None:
            with engine.begin() as connection:
                connection.execute(
                    text("""
                UPDATE audit.pipeline_runs
                SET status = 'FAILED', ended_at = CURRENT_TIMESTAMP,
                    current_stage = 'failed',
                    duration_seconds = :duration_seconds, error_message = :error_message
                    WHERE run_id = :run_id
                """),
                    {
                        "run_id": run_id,
                        "duration_seconds": round(perf_counter() - started, 3),
                        "error_message": str(error),
                    },
                )
                load_stage_runs(connection, run_id, stages)
        LOGGER.exception(
            "pipeline_run_failed",
            extra={
                "run_id": str(run_id) if run_id else None,
                "pipeline_name": settings.pipeline_name,
                "status": "FAILED",
                "start_time": run_started_at.isoformat(),
                "end_time": datetime.now(APP_TIMEZONE).isoformat(),
                "error_message": str(error),
            },
        )
        if run_id is not None:
            notify_pipeline_failure(run_id, str(error))
        raise


if __name__ == "__main__":
    run()
