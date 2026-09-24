"""Incremental reporting must count skipped occurrences, not unique hashes."""

from dataclasses import replace
from pathlib import Path

import pandas as pd

from pipeline.alerts import format_pipeline_report
from pipeline.extract.base import ExtractedSource, extract_delimited, filter_unseen_rows, raw_payload_hash
from pipeline.reporting import outcome_message, summarize_sources


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


def test_email_distinguishes_skips_from_dq_duplicates():
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
    }
    body = format_pipeline_report(report)
    assert "Total transaksi diperiksa: 120" in body
    assert "Data identik dilewati: 100" in body
    assert "Duplikat saat validasi: 3" in body
    assert "Data ditulis ke warehouse: 15" in body
    assert "Baris identik dilewati sebelum validasi ulang" in body


def test_success_report_uses_timestamps_and_has_no_error_section():
    body = format_pipeline_report({
        "status": "SUCCESS",
        "started_at": "2026-09-24T14:47:38.680184+07:00",
        "ended_at": "2026-09-24T14:47:53.153385+07:00",
        "duration_seconds": 1.154,
        "source_records": 984,
        "extracted_records": 0,
        "skipped_unchanged_records": 984,
        "loaded_records": 0,
    })
    assert "Status: BERHASIL" in body
    assert "Tidak ada data baru atau perubahan" in body
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
    assert "Tidak ada kandidat" in outcome_message(report)
