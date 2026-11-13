"""Pelaporan inkremental."""

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

from pipeline.alerts import format_pipeline_report
from pipeline.extract.base import ExtractedSource, extract_delimited, filter_unseen_rows, raw_payload_hash
from pipeline.logger import _PrettyConsoleFormatter
from pipeline.reporting import (
    DATABASE_COUNT_TABLES,
    auxiliary_source_summary,
    database_table_counts,
    outcome_message,
    quality_staging_summary,
    run_report_summary,
    summarize_sources,
)


def test_database_table_counts_uses_actual_table_counts():
    class Result:
        def scalar_one(self):
            return 7

    class Connection:
        def __init__(self):
            self.statements = []

        def execute(self, statement):
            self.statements.append(str(statement))
            return Result()

    connection = Connection()
    counts = database_table_counts(connection)

    assert tuple(counts) == DATABASE_COUNT_TABLES
    assert all(count == 7 for count in counts.values())
    assert len(connection.statements) == len(DATABASE_COUNT_TABLES)


def test_pipeline_log_includes_auxiliary_and_cumulative_database_counts():
    report_summary = {
        "raw": {},
        "warehouse": {},
        "auxiliary_sources": [
                {"source_name": "PROMO_MASTER", "source_records": 12, "processed": 12,
                 "validated": 12, "raw_inserted": 12, "warehouse_written": 12,
                 "promo_codes_checked": 187, "promo_codes_matched": 187},
            {"source_name": "RETURN_EVENTS", "source_records": 100, "processed": 100, "validated": 100,
             "raw_inserted": 100, "staging_written": 100, "warehouse_written": 100},
        ],
        "database_table_counts": {"raw.promo_master": 12, "raw.return_events": 100,
                                  "staging.stg_returns": 100, "warehouse.fact_returns": 100},
        "return_warehouse": {"eligible_facts": 100, "inserted_facts": 100,
                             "updated_facts": 0, "facts_written": 100},
    }
    source_metrics = [
        {"source_name": "SHOPEE", "source_records": 120, "extracted_records": 120,
         "validated_records": 112, "rejected_records": 7, "duplicate_records": 1},
        {"source_name": "TOKOPEDIA", "source_records": 120, "extracted_records": 120,
         "validated_records": 112, "rejected_records": 7, "duplicate_records": 1},
        {"source_name": "WEBSITE", "source_records": 120, "extracted_records": 120,
         "validated_records": 112, "rejected_records": 7, "duplicate_records": 1},
        {"source_name": "OFFLINE_STORE", "source_records": 120, "extracted_records": 120,
         "validated_records": 112, "rejected_records": 7, "duplicate_records": 1},
        {"source_name": "PRODUCT_MASTER", "source_records": 20, "extracted_records": 20,
         "validated_records": 20, "rejected_records": 0, "duplicate_records": 0},
    ]
    record = SimpleNamespace(
        report_summary=report_summary,
        source_metrics=source_metrics,
        status="SUCCESS",
        outcome_message="Pipeline selesai.",
    )

    output = _PrettyConsoleFormatter()._format_pipeline_completion(record)

    assert "Master Promo: katalog 12 | valid katalog 12 | baru/berubah 12" in output
    assert "Return: sumber 100" in output
    assert "Total baris semua sumber : 612" in output
    assert "Total valid              : 580" in output
    assert "Total ditolak            : 28" in output
    assert "Total duplikat           : 4" in output
    assert "Fact Return ditulis      : 100" in output
    assert "JUMLAH BARIS DALAM DATABASE" in output
    assert "raw.promo_master" in output and "12" in output
    assert "raw.return_events" in output and "100" in output
    assert "warehouse.fact_returns" in output
    assert "Staging dimuat 100" in output
    assert "staging.stg_returns" in output
    assert "QUALITY CHECK — RETURN" in output
    assert "Return dimuat ke Staging: 100" in output
    assert "Rincian alasan penolakan: tidak ada baris ditolak" not in output
    assert "RINCIAN VALIDASI PER SUMBER" not in output
    assert "Master Promo: katalog 12 | valid katalog 12 | baru/berubah 12" in output
    assert "Kode promo cocok 187/187" in output
    assert "Return: sumber 100 | berubah 100 | valid 100 | ditolak 0 | duplikat 0" in output
    for source_name in ("SHOPEE", "TOKOPEDIA", "WEBSITE", "OFFLINE_STORE"):
        assert f"{source_name}: sumber 120 | kandidat 120" in output


def test_auxiliary_summary_preserves_scope_and_noop_metrics():
    master = source([{}, {}], "PROMO_MASTER")
    returns = source([{}, {}, {}, {}], "RETURN_EVENTS")
    delta = source([], "RETURN_EVENTS")
    metrics = {"PROMO_MASTER": {"valid": 1, "duplicates": 1}}
    result = auxiliary_source_summary([master], [], metrics, returns, delta)
    assert result[0]["raw_inserted"] == 0
    assert result[0]["processed"] == 0
    assert result[0]["validated"] == 0
    assert result[0]["catalog_checked"] == 2
    assert result[0]["catalog_validated"] == 1
    assert result[0]["catalog_duplicates"] == 1
    assert result[0]["duplicates"] == 0
    assert result[1]["unchanged"] == 4
    assert result[1]["validated"] == 0
    assert result[1]["warehouse_written"] == 0


def test_auxiliary_summary_records_return_work_without_sales():
    returns = source([{}, {}, {}, {}], "RETURN_EVENTS")
    delta = source([{}, {}, {}], "RETURN_EVENTS")
    result = auxiliary_source_summary([], [], {}, returns, delta,
        return_result={"staged": 1, "loaded": 1, "valid": 1, "rejected": 1, "duplicates": 1,
                       "rejection_reasons": {"bad order": 1}})[0]
    assert result["raw_inserted"] == 3
    assert result["unchanged"] == 1
    assert result["warehouse_written"] == 1
    assert result["staging_written"] == 1
    assert result["duplicates"] == 1
    assert result["rejected"] == 1
    assert result["rejection_reasons"] == {"bad order": 1}


def test_return_quality_log_shows_rejection_reasons():
    record = SimpleNamespace(
        report_summary={
            "auxiliary_sources": [{
                "source_name": "RETURN_EVENTS", "source_records": 3, "processed": 3,
                "unchanged": 0, "validated": 2, "rejected": 1, "duplicates": 0,
                "staging_written": 2, "warehouse_written": 2,
                "rejection_reasons": {"Baris penjualan asal tidak ditemukan": 1},
            }],
            "return_warehouse": {"eligible_facts": 2, "inserted_facts": 2, "facts_written": 2},
        },
        source_metrics=[], status="SUCCESS", outcome_message="done",
    )

    output = _PrettyConsoleFormatter()._format_pipeline_completion(record)

    assert "QUALITY CHECK — RETURN" in output
    assert "- Ditolak: 1" in output
    assert "- Referensi transaksi tidak valid: 1" in output
    assert "Rincian: Baris penjualan asal tidak ditemukan: 1" in output
    assert "Baris penjualan asal tidak ditemukan: 1" in output


def test_return_quality_log_matches_sales_on_incremental_noop():
    record = SimpleNamespace(
        report_summary={"auxiliary_sources": [
            {"source_name": "PROMO_MASTER", "source_records": 12, "processed": 0,
             "catalog_checked": 0, "catalog_validated": 0, "validated": 0,
             "rejected": 0, "duplicates": 0, "raw_inserted": 0, "warehouse_written": 0},
            {"source_name": "RETURN_EVENTS", "source_records": 100, "processed": 0,
             "unchanged": 100, "validated": 0, "rejected": 0, "duplicates": 0,
             "raw_inserted": 0, "staging_written": 0, "warehouse_written": 0,
             "rejection_reasons": {}},
        ], "raw": {"product_master": {"new_or_changed": 0, "inserted_to_raw": 0, "total_in_raw": 20}},
            "dimensions": {"products_processed": 0}},
        source_metrics=[{"source_name": "PRODUCT_MASTER", "source_records": 20,
                         "extracted_records": 0, "validated_records": 0,
                         "rejected_records": 0, "duplicate_records": 0}],
        status="SUCCESS", outcome_message="done",
    )

    output = _PrettyConsoleFormatter()._format_pipeline_completion(record)

    section = output.split("QUALITY CHECK — RETURN", 1)[1].split("STAGING LAYER", 1)[0]
    assert "Tidak dijalankan karena tidak ada data baru atau perubahan." in section
    assert "Diperiksa:" not in section
    assert "Master Produk baru/berubah: 0 | Raw ditambah 0 | total Raw: 20" in output
    assert "Master Promo: katalog 12 | valid katalog 0 | baru/berubah 0 | ditolak 0 | duplikat 0" in output
    assert "Return: sumber 100 | berubah 0 | valid 0 | ditolak 0 | duplikat 0" in output
    source_details = output.split("RINCIAN PER SUMBER", 1)[1].split("RAW LAYER", 1)[0]
    assert "Raw ditambah 0" not in source_details
    assert "Dimensi Produk diproses 0" not in source_details
    assert "Staging dimuat 0" not in source_details
    assert "Fact ditulis 0" not in source_details


def source(rows, name="SHOPEE"):
    return ExtractedSource(
        name,
        "raw.shopee_orders",
        Path("unused.csv"),
        "CSV",
        pd.DataFrame(rows),
        {"order_id": "order_id"},
        source_records=len(rows),
    )


def test_duplicate_upload_is_counted_before_validation():
    old = {"order_id": "A"}
    new = {"order_id": "B"}
    scanned = source([old, old, new])
    delta = filter_unseen_rows(scanned, {raw_payload_hash(old)})
    result = summarize_sources([scanned], [delta])
    assert result["source_records"] == 3
    assert result["skipped_unchanged_records"] == 2
    assert result["source_metrics"][0]["extracted_records"] == 1


def test_unchanged_file_keeps_occurrence_count_without_parsing(tmp_path, monkeypatch):
    path = tmp_path / "shopee.csv"
    path.write_text("order_id\nA\nA\n", encoding="utf-8")
    first = extract_delimited("SHOPEE", "raw.shopee_orders", path, {"order_id": "order_id"})
    snapshot = {"file_checksum_sha256": first.checksum_sha256, "source_records": 2}

    def no_parse(*args, **kwargs):
        raise AssertionError("An unchanged file should not be parsed")

    monkeypatch.setattr("pipeline.validation.data_quality.read_source", no_parse)
    same = extract_delimited("SHOPEE", "raw.shopee_orders", path, {"order_id": "order_id"}, snapshot)
    metrics = summarize_sources([same], [same])
    assert same.frame.empty
    assert metrics["source_records"] == metrics["skipped_unchanged_records"] == 2


def test_old_snapshot_without_count_is_measured_once(tmp_path):
    path = tmp_path / "shopee.csv"
    path.write_text("order_id\nA\nA\n", encoding="utf-8")
    first = extract_delimited("SHOPEE", "raw.shopee_orders", path, {"order_id": "order_id"})
    snapshot = {"file_checksum_sha256": first.checksum_sha256, "source_records": None}
    measured = extract_delimited("SHOPEE", "raw.shopee_orders", path, {"order_id": "order_id"}, snapshot)
    delta = filter_unseen_rows(measured, {raw_payload_hash({"order_id": "A"})})
    assert measured.source_records == 2
    assert delta.frame.empty


def test_product_master_excluded_from_transaction_totals():
    sales = source([{"order_id": "A"}])
    master = replace(sales, source_name="PRODUCT_MASTER")
    result = summarize_sources([sales, master], [sales, master])
    assert result["source_records"] == 1
    assert len(result["source_metrics"]) == 2


def test_email_shows_processing_results_without_snapshot_metrics():
    report = {
        "status": "SUCCESS",
        "source_records": 120,
        "skipped_unchanged_records": 100,
        "extracted_records": 20,
        "duplicate_records": 3,
        "rejected_records": 2,
        "validated_records": 15,
        "loaded_records": 15,
        "fact_inserted_records": 15,
        "report_summary": {
            "raw": {
                "source_total": 120,
                "new_or_changed": 20,
                "inserted_to_raw": 20,
                "total_transactions_in_raw": 470,
                "product_master": {
                    "source_total": 20,
                    "new_or_changed": 20,
                    "inserted_to_raw": 20,
                    "total_in_raw": 20,
                },
            },
            "quality_staging": {
                "checked": True,
                "missing_value": {"total": 0, "by_field": {}},
                "duplicate_business_key": {"total": 3, "by_field": {"order_id": 3}},
                "invalid_quantity": {"total": 0, "by_field": {}},
                "invalid_price": {"total": 0, "by_field": {}},
                "invalid_status": {"total": 0, "by_field": {}},
                "invalid_date": {"total": 0, "by_field": {}},
                "unmapped_product": {"total": 0, "by_field": {}},
                "type_cast_failure": {"total": 0, "by_field": {}},
                "passed_to_staging": 15,
                "written_to_staging": 15,
            },
            "warehouse": {"eligible_facts": 15, "inserted_facts": 15, "updated_facts": 0, "facts_written": 15},
        },
    }
    body = format_pipeline_report(report)
    assert "Transaksi baru atau berubah: 20" in body
    assert "Master Produk diproses: 20" in body
    assert "Duplikat business key: 3" in body
    assert "Total fact ditulis: 15" in body
    assert "identik" not in body.lower()


def test_success_report_uses_timestamps_and_has_no_error_section():
    body = format_pipeline_report(
        {
            "status": "SUCCESS",
            "started_at": "2026-09-24T14:47:38.680184+07:00",
            "ended_at": "2026-09-24T14:47:53.153385+07:00",
            "duration_seconds": 1.154,
            "source_records": 984,
            "extracted_records": 0,
            "skipped_unchanged_records": 984,
            "loaded_records": 0,
        }
    )
    assert "Status:" not in body
    assert "tanpa data baru atau perubahan" in body
    assert "Durasi: 14.473 detik" in body
    assert "ERROR" not in body


def test_legacy_and_failed_reports_do_not_claim_no_new_data():
    assert "belum direkam" in outcome_message({"status": "SUCCESS"}).lower()
    assert "gagal" in outcome_message({"status": "FAILED", "source_records": 0}).lower()
    body = format_pipeline_report(
        {"status": "FAILED", "outcome_message": "Old success", "error_message": "snapshot lookup failed"}
    )
    assert "Old success" not in body
    assert "snapshot lookup failed" in body
    assert "Belum direkam" in body


def test_noop_is_success_with_explicit_explanation():
    report = {
        "status": "SUCCESS",
        "source_records": 120,
        "extracted_records": 0,
        "skipped_unchanged_records": 120,
        "loaded_records": 0,
    }
    assert "tanpa data baru atau perubahan" in outcome_message(report)


def test_noop_reports_deactivations_from_a_complete_snapshot():
    report = {
        "status": "SUCCESS",
        "extracted_records": 0,
        "source_reconciliation": [{"status": "SUCCESS", "deactivated_records": 12}],
    }

    assert "menonaktifkan 12 baris" in outcome_message(report)


def test_outcome_message_summarizes_all_sources_and_both_warehouse_facts():
    report = {
        "status": "SUCCESS",
        "extracted_records": 480,
        "loaded_records": 448,
        "source_metrics": [
            {"source_name": "PRODUCT_MASTER", "extracted_records": 20},
        ],
        "report_summary": {
            "auxiliary_sources": [
                {"source_name": "PROMO_MASTER", "processed": 12},
                {"source_name": "RETURN_EVENTS", "processed": 100, "warehouse_written": 100},
            ],
            "return_warehouse": {"facts_written": 100},
        },
    }

    assert outcome_message(report) == (
        "Pipeline berhasil memproses 612 baris dari seluruh sumber, 480 transaksi kanal, "
        "20 Master Produk, 12 Master Promo, dan 100 Return. Sebanyak 448 fact sales dan "
        "100 fact return dimuat ke warehouse."
    )


def test_report_includes_return_event_counts_when_present():
    body = format_pipeline_report(
        {
            "status": "SUCCESS",
            "report_summary": {
                "raw": {},
                "returns": {"raw_records_inserted": 4, "loaded_events": 3, "rejected_events": 1},
            },
        }
    )

    assert "RETUR & REFUND" in body
    assert "Event baru ke Raw: 4" in body
    assert "Event valid dimuat ke Warehouse: 3" in body
    assert "Event ditolak: 1" in body


def test_email_report_hides_reconciliation_details():
    body = format_pipeline_report(
        {
            "status": "SUCCESS",
            "report_summary": {
                "raw": {},
                "reconciliation": {"sources_checked": 1, "sources_skipped": 3, "deactivated_records": 12},
            },
        }
    )

    assert "REKONSILIASI SUMBER" not in body
    assert "Snapshot lengkap diperiksa" not in body


def test_run_summary_separates_run_metrics_from_table_inventory():
    summary = run_report_summary(
        {"source_records": 120, "extracted_records": 20},
        raw_inserted_records=20,
        raw_transaction_total=470,
        raw_product_master_total=20,
        raw_inserted_product_master_records=2,
        eligible_facts=15,
        inserted_facts=12,
        facts_written=15,
    )
    assert summary["raw"] == {
        "source_total": 120,
        "new_or_changed": 20,
        "inserted_to_raw": 20,
        "total_transactions_in_raw": 470,
        "product_master": {
            "source_total": 0,
            "new_or_changed": 0,
            "inserted_to_raw": 2,
            "total_in_raw": 20,
        },
    }
    assert summary["warehouse"] == {
        "eligible_facts": 15,
        "inserted_facts": 12,
        "updated_facts": 3,
        "facts_written": 15,
    }


def test_quality_summary_keeps_detailed_sources_but_excludes_product_from_transaction_total():
    sales = SimpleNamespace(
        issues=pd.DataFrame(
            [
                {"rule": "INVALID_DATE", "field": "order_date"},
                {"rule": "DUPLICATE_BUSINESS_KEY", "field": "business_key"},
            ]
        ),
        summary={"extracted_records": 4, "valid_records": 2, "invalid_records": 1, "duplicate_records": 1},
    )
    product = SimpleNamespace(
        issues=pd.DataFrame([{"rule": "MISSING_REQUIRED", "field": "sku"}]),
        summary={"extracted_records": 2, "valid_records": 1, "invalid_records": 1, "duplicate_records": 0},
    )
    summary = quality_staging_summary({"shopee": sales, "product": product}, passed_to_staging=2, written_to_staging=2)
    assert summary["invalid_date"]["total"] == 1
    assert summary["duplicate_business_key"]["total"] == 1
    assert summary["missing_value"]["total"] == 0
    assert [item["source_name"] for item in summary["by_source"]] == ["SHOPEE", "PRODUCT_MASTER"]
