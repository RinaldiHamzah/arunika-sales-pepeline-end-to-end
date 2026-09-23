"""Run extraction and raw ingestion: python -m pipeline.runner."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from time import perf_counter
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import text

from pipeline.alerts import notify_pipeline_failure, send_pipeline_report
from pipeline.config import settings
from pipeline.database import get_engine
from pipeline.execution import begin_run, pipeline_lock
from pipeline.extract.base import filter_unseen_rows
from pipeline.extract.sources import extract_all
from pipeline.load.audit_loader import load_quality_audit, load_stage_runs, update_watermarks
from pipeline.load.dimension_loader import load_dimensions
from pipeline.load.fact_loader import load_facts
from pipeline.load.raw_loader import load_raw, load_source_snapshots, save_source_snapshots
from pipeline.load.staging_loader import load_staging
from pipeline.logger import get_logger
from pipeline.reporting import outcome_message, summarize_sources
from pipeline.transform.standardize import clean_results_to_staging, filter_incremental_results
from pipeline.validation.data_quality import run_quality

# Keep a stable logger name when this module is executed both as an import and
# via ``python -m pipeline.runner``. The latter sets ``__name__`` to
# ``__main__``; a stable name ensures the event is routed to pipeline.log.
LOGGER = get_logger("pipeline.runner")
SOURCE_DIR = Path(__file__).resolve().parents[1] / "data" / "source"
APP_TIMEZONE = ZoneInfo(settings.app_timezone)


def _send_direct_run_report(engine, run_id, orchestration_run_id) -> bool:
    """Email an audit-backed report for CLI and dashboard executions only.

    Airflow has its own terminal ``email_pipeline_report`` task.  Skipping an
    orchestrated run here guarantees a scheduled DAG produces exactly one
    report, while ``python -m pipeline.runner`` and the dashboard still notify
    the configured recipient.
    """
    if orchestration_run_id:
        return False

    try:
        with engine.connect() as connection:
            report = (
                connection.execute(
                    text("""
                        SELECT run_id, status, started_at, ended_at, duration_seconds,
                               extracted_records, validated_records, rejected_records,
                               duplicate_records, incremental_records, fact_inserted_records,
                               fact_skipped_records, loaded_records, error_message,
                               source_records, skipped_unchanged_records, source_metrics, outcome_message
                        FROM audit.pipeline_runs
                        WHERE run_id = :run_id
                    """),
                    {"run_id": run_id},
                )
                .mappings()
                .one_or_none()
            )
        if report is None:
            LOGGER.warning("pipeline_email_report_skipped", extra={"run_id": str(run_id), "status": "NO_AUDIT_RUN"})
            return False
        return send_pipeline_report(dict(report))
    except Exception:
        # Notification failures must not change the ETL result or mask its
        # original exception.  The structured log retains the diagnosis.
        LOGGER.exception("pipeline_email_report_unavailable", extra={"run_id": str(run_id)})
        return False


def run(source_dir: Path | None = None, *, reserved_run_id=None, orchestration_run_id=None):
    engine = get_engine()
    try:
        with pipeline_lock(engine):
            return _run(engine, source_dir, reserved_run_id, orchestration_run_id)
    finally:
        engine.dispose()


def _run(engine, source_dir, reserved_run_id, orchestration_run_id):
    started = perf_counter()
    run_started_at = datetime.now(APP_TIMEZONE)
    stages = []
    report_metrics = {}
    source_dir = Path(source_dir) if source_dir else SOURCE_DIR
    run_id = begin_run(engine, settings.pipeline_name, reserved_run_id, orchestration_run_id)

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
        try:
            mark_current_stage(name)
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

    try:
        with engine.connect() as connection:
            snapshots = stage("snapshot_lookup", lambda: load_source_snapshots(connection))
        scanned_sources = stage("source_scan", lambda: extract_all(source_dir, snapshots))
        known_hashes = {
            source.source_name: set(snapshots.get(source.source_name, {}).get("payload_hashes", []))
            for source in scanned_sources
        }
        sources = stage(
            "incremental_extract",
            lambda: [filter_unseen_rows(source, known_hashes[source.source_name]) for source in scanned_sources],
        )
        stages[-1]["records_processed"] = sum(len(source.frame) for source in sources)
        extracted_count = sum(len(source.frame) for source in sources if source.source_name != "PRODUCT_MASTER")
        report_metrics = summarize_sources(scanned_sources, sources)
        with engine.begin() as connection:
            connection.execute(
                text("""
                UPDATE audit.pipeline_runs
                SET extracted_records = :extracted_records,
                    source_records=:source_records, skipped_unchanged_records=:skipped_unchanged_records,
                    source_metrics=CAST(:source_metrics AS JSONB)
                WHERE run_id = :run_id
            """),
                {
                    "run_id": run_id,
                    "extracted_records": extracted_count,
                    **report_metrics,
                    "source_metrics": json.dumps(report_metrics["source_metrics"]),
                },
            )

        selected_rows = {
            source.source_name.lower().replace("_store", ""): source.row_numbers
            for source in sources
            if source.source_name != "PRODUCT_MASTER"
        }
        captured_sources = {
            (
                "product"
                if source.source_name == "PRODUCT_MASTER"
                else source.source_name.lower().replace("_store", "")
            ): (source.frame.copy(), source.checksum_sha256)
            for source in scanned_sources
        }
        quality_results = stage(
            "validate",
            lambda: run_quality(source_dir, selected_row_numbers=selected_rows, captured_sources=captured_sources),
        )
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
        product_source = next(source for source in sources if source.source_name == "PRODUCT_MASTER")
        product_rows = quality_results["product"].clean
        # Product Master remains available in full for sales mapping, but only
        # raw rows whose payload changed are upserted to the dimension.
        product_delta = product_rows[product_rows["source_row_number"].isin(product_source.row_numbers)].reset_index(
            drop=True
        )
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
            dimension_counts = stage("dimension_load", lambda: load_dimensions(connection, product_delta, staging_rows))
            stages[-1]["records_processed"] = sum(dimension_counts.values())
            fact_before = connection.execute(text("SELECT COUNT(*) FROM warehouse.fact_sales")).scalar_one()
            fact_count = stage("fact_load", lambda: load_facts(connection, run_id))
            stages[-1]["records_processed"] = fact_count
            fact_after = connection.execute(text("SELECT COUNT(*) FROM warehouse.fact_sales")).scalar_one()
            fact_inserted_count = max(int(fact_after) - int(fact_before), 0)
            incremental_count = len(staging_rows)
            fact_skipped_count = max(valid_count - incremental_count, 0)
            report_metrics["outcome_message"] = outcome_message(
                {
                    **report_metrics,
                    "status": "SUCCESS",
                    "extracted_records": extracted_count,
                    "loaded_records": fact_count,
                }
            )
            for detail in report_metrics["source_metrics"]:
                key = (
                    "product"
                    if detail["source_name"] == "PRODUCT_MASTER"
                    else detail["source_name"].lower().replace("_store", "")
                )
                result = quality_results[key].summary
                detail.update(
                    validated_records=result["valid_records"],
                    rejected_records=result["invalid_records"],
                    duplicate_records=result["duplicate_records"],
                )
            save_source_snapshots(connection, run_id, scanned_sources, snapshots)
            load_quality_audit(connection, run_id, quality_results)
            update_watermarks(connection, run_id, quality_results)
            load_stage_runs(connection, run_id, stages)
            connection.execute(
                text("""
                UPDATE audit.pipeline_runs
                SET status = 'SUCCESS', ended_at = CURRENT_TIMESTAMP,
                    current_stage = 'completed', outcome_message=:outcome_message,
                    source_metrics=CAST(:source_metrics AS JSONB),
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
                    "outcome_message": report_metrics["outcome_message"],
                    "source_metrics": json.dumps(report_metrics["source_metrics"]),
                    "valid_records": valid_count,
                    "duplicate_records": duplicate_count,
                    "invalid_records": invalid_count,
                    # ``loaded_records`` counts fact rows written (inserted or
                    # corrected by UPSERT); ``fact_inserted_records`` remains
                    # the narrower physical-insert metric.
                    "loaded_records": fact_count,
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
                **report_metrics,
                "run_id": str(run_id),
                "pipeline_name": settings.pipeline_name,
                "status": "SUCCESS",
                "start_time": run_started_at.isoformat(),
                "end_time": run_ended_at.isoformat(),
                "extracted_records": extracted_count,
                "valid_records": valid_count,
                "duplicate_records": duplicate_count,
                "invalid_records": invalid_count,
                "loaded_records": fact_count,
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
        _send_direct_run_report(engine, run_id, orchestration_run_id)
        return run_id
    except Exception as error:
        try:
            if run_id is not None:
                with engine.begin() as connection:
                    connection.execute(
                        text("""
                    UPDATE audit.pipeline_runs
                    SET status = 'FAILED', ended_at = CURRENT_TIMESTAMP,
                        current_stage = 'failed', outcome_message='Pipeline gagal. Lihat error_message.',
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
        except Exception:
            LOGGER.exception("pipeline_failure_audit_unavailable", extra={"run_id": str(run_id)})
        LOGGER.exception(
            "pipeline_run_failed",
            extra={
                **report_metrics,
                "outcome_message": outcome_message({"status": "FAILED"}),
                "run_id": str(run_id) if run_id else None,
                "pipeline_name": settings.pipeline_name,
                "status": "FAILED",
                "start_time": run_started_at.isoformat(),
                "end_time": datetime.now(APP_TIMEZONE).isoformat(),
                "error_message": str(error),
            },
        )
        if run_id is not None:
            _send_direct_run_report(engine, run_id, orchestration_run_id)
            try:
                notify_pipeline_failure(run_id, str(error))
            except Exception:
                LOGGER.exception("pipeline_failure_alert_unavailable", extra={"run_id": str(run_id)})
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", type=UUID, help="Claim a dashboard reservation")
    args = parser.parse_args()
    run(reserved_run_id=args.run_id)
