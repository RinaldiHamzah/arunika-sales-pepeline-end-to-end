"""Jalankan ekstraksi dan pemuatan data.
Contoh perintah: python -m pipeline.runner
"""

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
from pipeline.load.fact_loader import load_facts, reconcile_source_snapshot
from pipeline.load.promotion_loader import load_promotion_dimension, load_promotion_raw
from pipeline.load.raw_loader import load_raw, load_source_snapshots, save_source_snapshots
from pipeline.load.return_loader import load_return_events, load_return_raw
from pipeline.load.staging_loader import load_staging
from pipeline.logger import get_logger
from pipeline.promotions import apply_order_promotions, extract_promotion_sources, snapshot_source
from pipeline.reporting import outcome_message, quality_staging_summary, run_report_summary, summarize_sources
from pipeline.returns import extract_return_events
from pipeline.source_manifest import load_source_manifest
from pipeline.transform.standardize import SOURCE_NAMES, clean_results_to_staging, filter_incremental_results
from pipeline.validation.data_quality import run_quality

# Gunakan nama logger yang tetap saat modul dipanggil sebagai impor maupun
# melalui ``python -m pipeline.runner``. Cara kedua mengatur ``__name__`` menjadi
# ``__main__``; nama yang tetap memastikan log masuk ke pipeline.log.
LOGGER = get_logger("pipeline.runner")
SOURCE_DIR = Path(__file__).resolve().parents[1] / "data" / "source"
APP_TIMEZONE = ZoneInfo(settings.app_timezone)

RAW_TRANSACTION_COUNT = text("""
    SELECT
        (SELECT COUNT(*) FROM raw.shopee_orders)
      + (SELECT COUNT(*) FROM raw.tokopedia_transactions)
      + (SELECT COUNT(*) FROM raw.website_transactions)
      + (SELECT COUNT(*) FROM raw.offline_store_sales)
""")
RAW_PRODUCT_MASTER_COUNT = text("SELECT COUNT(*) FROM raw.product_master")


def raw_transaction_total(connection) -> int:
    """Kembalikan inventaris transaksi saat ini di Raw Layer."""
    return int(connection.execute(RAW_TRANSACTION_COUNT).scalar_one())


def raw_product_master_total(connection) -> int:
    """Kembalikan inventaris Product Master saat ini di Raw Layer."""
    return int(connection.execute(RAW_PRODUCT_MASTER_COUNT).scalar_one())


def existing_fact_hashes(engine, quality_results) -> dict[tuple[str, str, int], str | None]:
    """Ambil hash gudang data hanya untuk key kandidat valid pada run ini."""
    source_names = []
    order_ids = []
    line_numbers = []
    for source, result in quality_results.items():
        if source == "product" or result.clean.empty:
            continue
        clean = result.clean
        source_names.extend([SOURCE_NAMES[source]] * len(clean))
        order_ids.extend(clean["order_id"].astype(str).tolist())
        line_numbers.extend(clean["line_number"].astype(int).tolist())

    if not source_names:
        return {}

    with engine.connect() as connection:
        rows = connection.execute(
            text("""
                SELECT fact.source_name, fact.source_order_id, fact.source_line_number,
                       CASE WHEN fact.is_source_active THEN fact.source_record_hash ELSE NULL END
                           AS source_record_hash
                FROM warehouse.fact_sales AS fact
                JOIN unnest(
                    CAST(:source_names AS VARCHAR[]),
                    CAST(:order_ids AS TEXT[]),
                    CAST(:line_numbers AS INTEGER[])
                ) AS candidate(source_name, source_order_id, source_line_number)
                  ON candidate.source_name = fact.source_name
                 AND candidate.source_order_id = fact.source_order_id
                 AND candidate.source_line_number = fact.source_line_number
            """),
            {
                "source_names": source_names,
                "order_ids": order_ids,
                "line_numbers": line_numbers,
            },
        ).mappings()
        return {
            (row["source_name"], row["source_order_id"], row["source_line_number"]): row["source_record_hash"]
            for row in rows
        }


def _send_direct_run_report(engine, run_id, orchestration_run_id) -> bool:
    """Kirim laporan berbasis audit hanya untuk eksekusi CLI dan dashboard.

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
                               source_records, skipped_unchanged_records, source_metrics, report_summary,
                               outcome_message
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
        # Kegagalan notifikasi tidak boleh mengubah hasil ETL atau menutupi
        # pengecualian awal. Log terstruktur tetap menyimpan penyebabnya.
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
    snapshot_sources = []
    source_dir = Path(source_dir) if source_dir else SOURCE_DIR
    run_id = begin_run(engine, settings.pipeline_name, reserved_run_id, orchestration_run_id)

    def mark_current_stage(name: str) -> None:
        """Simpan awal tahap segera agar UI dapat menampilkan progres langsung."""
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

    def finish_incremental_noop():
        """Selesaikan run tanpa perubahan tanpa menyentuh kualitas, staging, atau fact."""
        duration_seconds = round(perf_counter() - started, 3)
        with engine.begin() as connection:
            reconciliation = stage(
                "source_reconciliation",
                lambda: reconcile_source_snapshot(connection, run_id, reconciliation_sources, declarations),
            )
            report_metrics["source_reconciliation"] = reconciliation
            stages[-1]["records_processed"] = sum(item["deactivated_records"] for item in reconciliation)
            message = outcome_message(
                {**report_metrics, "status": "SUCCESS", "extracted_records": 0, "loaded_records": 0}
            )
            report_metrics["report_summary"] = run_report_summary(
                report_metrics,
                raw_transaction_total=raw_transaction_total(connection),
                raw_product_master_total=raw_product_master_total(connection),
                source_reconciliation=reconciliation,
            )
            # CSV yang disusun ulang tetapi isinya sama tetap mendapat checksum terbaru.
            # Tidak ada baris yang dimuat ke raw karena seluruh payload sudah tercatat.
            save_source_snapshots(connection, run_id, snapshot_sources, snapshots)
            load_stage_runs(connection, run_id, stages)
            connection.execute(
                text("""
                    UPDATE audit.pipeline_runs
                    SET status = 'SUCCESS', ended_at = CURRENT_TIMESTAMP,
                        current_stage = 'completed', outcome_message = :outcome_message,
                        report_summary = CAST(:report_summary AS JSONB),
                        valid_records = 0, duplicate_records = 0, invalid_records = 0,
                        loaded_records = 0, validated_records = 0, rejected_records = 0,
                        incremental_records = 0, staged_records = 0, dimension_records = 0,
                        fact_inserted_records = 0, fact_skipped_records = 0,
                        duration_seconds = :duration_seconds
                    WHERE run_id = :run_id
                """),
                {
                    "run_id": run_id,
                    "outcome_message": message,
                    "report_summary": json.dumps(report_metrics["report_summary"]),
                    "duration_seconds": duration_seconds,
                },
            )
        run_ended_at = datetime.now(APP_TIMEZONE)
        LOGGER.info(
            "pipeline_run_completed",
            extra={
                **report_metrics,
                "outcome_message": message,
                "run_id": str(run_id),
                "pipeline_name": settings.pipeline_name,
                "status": "SUCCESS",
                "start_time": run_started_at.isoformat(),
                "end_time": run_ended_at.isoformat(),
                "extracted_records": 0,
                "valid_records": 0,
                "duplicate_records": 0,
                "invalid_records": 0,
                "loaded_records": 0,
                "validated_records": 0,
                "rejected_records": 0,
                "incremental_records": 0,
                "staged_records": 0,
                "dimension_records": 0,
                "fact_inserted_records": 0,
                "fact_skipped_records": 0,
                "duration_seconds": duration_seconds,
                "error_message": None,
            },
        )
        _send_direct_run_report(engine, run_id, orchestration_run_id)
        return run_id

    try:
        with engine.connect() as connection:
            snapshots = stage("snapshot_lookup", lambda: load_source_snapshots(connection))
        declarations = stage("source_manifest", lambda: load_source_manifest(source_dir))
        promo_sources = stage("promotion_scan", lambda: extract_promotion_sources(source_dir))
        return_source = stage("return_scan", lambda: extract_return_events(source_dir, snapshots.get("RETURN_EVENTS")))
        promo_changed = any(
            snapshots.get(source.source_name, {}).get("file_checksum_sha256") != source.checksum_sha256
            for source in promo_sources
        )
        promotion_checksum = ":".join(source.checksum_sha256 for source in promo_sources)
        has_full_snapshot = any(declaration.is_reconcilable for declaration in declarations.values())
        scanned_sources = stage(
            "source_scan",
            lambda: extract_all(source_dir, snapshots, force_refresh=promo_changed or has_full_snapshot),
        )
        effective_scanned_sources, promotion_master = stage(
            "promotion_match", lambda: apply_order_promotions(scanned_sources, promo_sources)
        )
        channel_names = set(SOURCE_NAMES.values())
        reconciliation_sources = [source for source in effective_scanned_sources if source.source_name in channel_names]
        raw_hashes = {
            source.source_name: set(snapshots.get(source.source_name, {}).get("payload_hashes", []))
            for source in scanned_sources
        }
        raw_deltas = stage(
            "raw_incremental_extract",
            lambda: [filter_unseen_rows(source, raw_hashes[source.source_name]) for source in scanned_sources],
        )
        effective_hashes = {
            source.source_name: set(
                snapshots.get(f"{source.source_name}_EFFECTIVE", snapshots.get(source.source_name, {})).get(
                    "payload_hashes", []
                )
            )
            for source in effective_scanned_sources
        }
        sources = stage(
            "incremental_extract",
            lambda: [
                filter_unseen_rows(source, effective_hashes[source.source_name]) for source in effective_scanned_sources
            ],
        )
        promo_deltas = [
            source
            for source in promo_sources
            if snapshots.get(source.source_name, {}).get("file_checksum_sha256") != source.checksum_sha256
        ]
        return_source_hashes = set(snapshots.get("RETURN_EVENTS", {}).get("payload_hashes", []))
        return_delta = stage(
            "return_incremental_extract", lambda: filter_unseen_rows(return_source, return_source_hashes)
        )
        snapshot_sources = [
            *scanned_sources,
            *[
                snapshot_source(source, effective=True, promotion_checksum=promotion_checksum)
                for source in effective_scanned_sources
                if source.source_name != "PRODUCT_MASTER"
            ],
            *promo_sources,
            return_source,
        ]
        stages[-1]["records_processed"] = sum(len(source.frame) for source in sources)
        extracted_count = sum(len(source.frame) for source in sources if source.source_name != "PRODUCT_MASTER")
        report_metrics = {
            **summarize_sources(scanned_sources, sources),
            "extracted_records": extracted_count,
        }
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

        # Kelima sumber, termasuk Product Master, tidak berubah. Pemeriksaan
        # snapshot sudah cukup; jangan jalankan pemeriksaan kualitas, staging,
        # atau kueri gudang data hanya untuk memastikan tidak ada pekerjaan.
        if not any(len(source.frame) for source in sources) and not promo_changed and return_delta.frame.empty:
            return finish_incremental_noop()

        # Raw adalah lapisan pendaratan yang tidak diubah. Simpan setiap payload
        # sumber yang baru atau berubah sebelum aturan kualitas atau transformasi
        # mengubah penafsirannya. Record tidak valid tetap dapat ditelusuri di raw
        # dan bukti audit, tetapi tidak diteruskan ke staging.
        with engine.begin() as connection:
            loaded_count = stage("raw_load", lambda: sum(load_raw(connection, run_id, source) for source in raw_deltas))
            stages[-1]["records_processed"] = loaded_count
            promotion_raw_count = stage(
                "promotion_raw_load", lambda: load_promotion_raw(connection, run_id, promo_deltas)
            )
            stages[-1]["records_processed"] = promotion_raw_count
            return_raw_count = 0
            if not return_delta.frame.empty:
                return_raw_count = stage("return_raw_load", lambda: load_return_raw(connection, run_id, return_delta))
                stages[-1]["records_processed"] = return_raw_count
            raw_total_after = raw_transaction_total(connection)
            raw_product_master_total_after = raw_product_master_total(connection)

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
            for source in effective_scanned_sources
        }
        quality_results = stage(
            "validate",
            lambda: run_quality(source_dir, selected_row_numbers=selected_rows, captured_sources=captured_sources),
        )
        stages[-1]["records_processed"] = sum(len(result.clean) for result in quality_results.values())
        existing_keys = stage("fact_lookup", lambda: existing_fact_hashes(engine, quality_results))
        incremental_results = stage(
            "incremental_filter", lambda: filter_incremental_results(quality_results, existing_keys)
        )
        staging_rows = stage("transform", lambda: clean_results_to_staging(incremental_results))
        stages[-1]["records_processed"] = len(staging_rows)
        product_source = next(source for source in raw_deltas if source.source_name == "PRODUCT_MASTER")
        product_rows = quality_results["product"].clean
        # Seluruh Product Master tetap tersedia untuk pemetaan penjualan, tetapi
        # hanya baris raw dengan payload berubah yang di-upsert ke dimensi.
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
            staged_count = stage("staging_load", lambda: load_staging(connection, run_id, staging_rows))
            stages[-1]["records_processed"] = staged_count
            dimension_counts = stage(
                "dimension_load",
                lambda: {
                    **load_dimensions(connection, product_delta, staging_rows),
                    "promotions": load_promotion_dimension(connection, promotion_master),
                },
            )
            stages[-1]["records_processed"] = sum(dimension_counts.values())
            fact_inserted_count = sum(
                (
                    row.source_name,
                    row.source_order_id,
                    int(row.source_line_number),
                )
                not in existing_keys
                for row in staging_rows.itertuples(index=False)
            )
            fact_count = stage("fact_load", lambda: load_facts(connection, run_id))
            stages[-1]["records_processed"] = fact_count
            reconciliation = stage(
                "source_reconciliation",
                lambda: reconcile_source_snapshot(connection, run_id, reconciliation_sources, declarations),
            )
            report_metrics["source_reconciliation"] = reconciliation
            stages[-1]["records_processed"] = sum(item["deactivated_records"] for item in reconciliation)
            return_summary = {"loaded": 0, "rejected": 0}
            if not return_delta.frame.empty:
                return_summary = stage(
                    "return_validation_load", lambda: load_return_events(connection, run_id, return_delta)
                )
                stages[-1]["records_processed"] = return_summary["loaded"] + return_summary["rejected"]
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
            report_metrics["report_summary"] = run_report_summary(
                report_metrics,
                # Laporan merangkum alur transaksi. Product Master juga dimuat
                # ke raw, tetapi merupakan data referensi, bukan transaksi,
                # sehingga tidak dihitung dalam jumlah ini.
                raw_inserted_records=sum(
                    len(source.frame) for source in raw_deltas if source.source_name != "PRODUCT_MASTER"
                ),
                raw_transaction_total=raw_total_after,
                raw_product_master_total=raw_product_master_total_after,
                raw_inserted_product_master_records=len(product_source.frame),
                quality_staging=quality_staging_summary(
                    quality_results,
                    passed_to_staging=incremental_count,
                    written_to_staging=staged_count,
                ),
                eligible_facts=incremental_count,
                inserted_facts=fact_inserted_count,
                facts_written=fact_count,
                source_reconciliation=reconciliation,
            )
            report_metrics["report_summary"]["returns"] = {
                "raw_records_inserted": return_raw_count,
                "loaded_events": return_summary["loaded"],
                "rejected_events": return_summary["rejected"],
            }
            report_metrics["report_summary"]["source_reconciliation"] = reconciliation
            save_source_snapshots(connection, run_id, snapshot_sources, snapshots)
            load_quality_audit(connection, run_id, quality_results)
            update_watermarks(connection, run_id, quality_results)
            load_stage_runs(connection, run_id, stages)
            connection.execute(
                text("""
                UPDATE audit.pipeline_runs
                SET status = 'SUCCESS', ended_at = CURRENT_TIMESTAMP,
                    current_stage = 'completed', outcome_message=:outcome_message,
                    source_metrics=CAST(:source_metrics AS JSONB),
                    report_summary=CAST(:report_summary AS JSONB),
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
                    "report_summary": json.dumps(report_metrics["report_summary"]),
                    "valid_records": valid_count,
                    "duplicate_records": duplicate_count,
                    "invalid_records": invalid_count,
                    # ``loaded_records`` menghitung baris fact yang ditulis
                    # (disisipkan atau dikoreksi melalui UPSERT); ``fact_inserted_records``
                    # tetap menjadi metrik khusus untuk penyisipan fisik.
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
