"""Tes integrasi basis data PostgreSQL."""

import csv
import json
import os
import shutil
import tempfile
import time
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from pipeline.database import get_engine
from pipeline.runner import run

pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]


def _enabled():
    return (
        os.getenv("RUN_POSTGRES_TESTS", "0") == "1"
        and os.getenv("ARUNIKA_ISOLATED_TEST_DATABASE", "0") == "1"
        and os.getenv("DATABASE_URL", "").rstrip("/").endswith("/ecommerce_sales_test")
    )


def _counts(connection):
    return {
        "raw": sum(
            connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
            for table in (
                "raw.shopee_orders",
                "raw.tokopedia_transactions",
                "raw.website_transactions",
                "raw.offline_store_sales",
                "raw.product_master",
            )
        ),
        "staging": connection.execute(text("SELECT COUNT(*) FROM staging.stg_sales")).scalar_one(),
        "return_staging": connection.execute(text("SELECT COUNT(*) FROM staging.stg_returns")).scalar_one(),
        "products": connection.execute(text("SELECT COUNT(*) FROM warehouse.dim_product")).scalar_one(),
        "facts": connection.execute(text("SELECT COUNT(*) FROM warehouse.fact_sales")).scalar_one(),
    }


def _reset_isolated_database(engine) -> None:
    """Kosongkan hanya basis data yang secara eksplisit ditandai untuk tes penerimaan.

    Docker dapat mempertahankan container tes di antara beberapa run. Mengosongkan
    seluruh tabel proyek membuat tes deterministik, sementara Alembic tetap menjaga
    skema dan versi migrasi.
    """
    assert _enabled(), "Pengosongan data tes memerlukan penanda basis data terisolasi."
    with engine.begin() as connection:
        tables = connection.execute(
            text("""
                SELECT table_schema, table_name
                FROM information_schema.tables
                WHERE table_type = 'BASE TABLE'
                  AND table_schema IN ('raw', 'staging', 'warehouse', 'audit')
                ORDER BY table_schema, table_name
            """)
        ).all()
        targets = ", ".join(f'"{schema}"."{table}"' for schema, table in tables)
        if targets:
            connection.execute(text(f"TRUNCATE TABLE {targets} RESTART IDENTITY CASCADE"))


def _append_valid_website_rows(source_dir, count=20):
    path = Path(source_dir) / "website.csv"
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
        fields = rows[0].keys()
    template = next(row for row in rows if row["status"] == "completed")
    test_batch = uuid4().hex[:12].upper()
    for index in range(count):
        row = dict(template)
        # Business key unik membuat tes dapat diulang pada basis data pengembangan
        # yang datanya tetap tersimpan setelah tes penerimaan sebelumnya.
        row["invoice_no"] = f"WEB-TEST-{test_batch}-{index:04d}"
        # Sebagian fixture sumber sengaja memiliki total_amount yang tidak cocok.
        # Batch incremental di sini harus valid agar benar-benar menguji pemuatan.
        gross = Decimal(row["quantity"]) * Decimal(row["unit_price"])
        discount = Decimal(row.get("discount_amount") or "0")
        row["total_amount"] = str((gross - discount).quantize(Decimal("0.01")))
        rows.append(row)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _source_row_count(source_dir):
    return sum(
        len(list(csv.DictReader((Path(source_dir) / name).open(encoding="utf-8", newline=""))))
        for name in ("product_master.csv", "shopee.csv", "tokopedia.csv", "website.csv", "offline.csv")
    )


def _website_order_lines(source_dir, order_id, count, changed_line=None):
    """Tambahkan atau ubah satu pesanan tanpa menyentuh baris sumber lain."""
    path = Path(source_dir) / "website.csv"
    with path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
        fields = list(rows[0])
    template = next(row for row in rows if row["status"] == "completed")
    rows = [row for row in rows if row["invoice_no"] != order_id]
    for line in range(1, count + 1):
        row = dict(template)
        row.update(invoice_no=order_id, line_item_no=str(line), quantity="4" if line == changed_line else "1")
        gross = Decimal(row["quantity"]) * Decimal(row["unit_price"])
        discount = Decimal(row.get("discount_amount") or "0")
        row["total_amount"] = str((gross - discount).quantize(Decimal("0.01")))
        rows.append(row)
    with path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _declare_website_snapshot(source_dir, *, mode, completeness, timestamp="2026-11-10T00:00:00+07:00"):
    manifest_path = Path(source_dir) / "source_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["sources"]["WEBSITE"] = {
        "ingestion_mode": mode,
        "snapshot_scope": "ALL_HISTORY" if mode == "FULL_SNAPSHOT" else None,
        "snapshot_timestamp": timestamp if mode == "FULL_SNAPSHOT" else None,
        "snapshot_completeness": completeness,
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


@pytest.mark.skipif(
    not _enabled(),
    reason="run against the isolated ecommerce_sales_test database via the test compose profile",
)
def test_full_pipeline_and_incremental_acceptance(monkeypatch):
    # OneDrive pada Windows dapat mengunci ``tmp_path`` pytest maupun folder repositori.
    # Gunakan folder khusus pada direktori sementara sistem operasi.
    runtime_root = Path(os.getenv("ARUNIKA_TEST_RUNTIME", str(Path(tempfile.gettempdir()) / "arunika_ecommerce_tests")))
    runtime_root.mkdir(exist_ok=True)
    source_dir = Path(tempfile.mkdtemp(dir=runtime_root)) / "source"
    source_dir.mkdir()
    for name in (
        "product_master.csv",
        "shopee.csv",
        "tokopedia.csv",
        "website.csv",
        "offline.csv",
        "promo_master.csv",
        "return_refund.csv",
    ):
        shutil.copy2(ROOT / "data" / "source" / name, source_dir / name)
    with (source_dir / "return_refund.csv").open(newline="", encoding="utf-8") as file:
        expected_return_rows = len(list(csv.DictReader(file)))
    (source_dir / "source_manifest.json").write_text(
        json.dumps(
            {
                "sources": {
                    source: {
                        "ingestion_mode": "FULL_SNAPSHOT",
                        "snapshot_scope": "ALL_HISTORY",
                        "snapshot_timestamp": "2026-11-10T00:00:00+07:00",
                        "snapshot_completeness": "COMPLETE",
                    }
                    for source in ("SHOPEE", "TOKOPEDIA", "WEBSITE", "OFFLINE_STORE")
                }
            }
        ),
        encoding="utf-8",
    )
    engine = get_engine()
    _reset_isolated_database(engine)
    with engine.connect() as connection:
        before = _counts(connection)
        required = connection.execute(
            text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE (table_schema, table_name) IN
              (('raw', 'shopee_orders'), ('staging', 'stg_sales'),
               ('warehouse', 'fact_sales'), ('warehouse', 'dim_product'),
               ('audit', 'pipeline_runs'), ('raw', 'return_events'),
               ('warehouse', 'fact_returns'), ('audit', 'source_reconciliations'),
               ('audit', 'stale_fact_corrections'),
               ('staging', 'stg_returns'))
        """)
        ).scalar_one()
        if required != 10:
            pytest.fail("Database schema is not initialized; load database/schema/*.sql first")

    run(source_dir)
    with engine.connect() as connection:
        first = _counts(connection)
        first_successes = connection.execute(
            text("SELECT COUNT(*) FROM audit.pipeline_runs WHERE status = 'SUCCESS'")
        ).scalar_one()
        first_run_id = connection.execute(
            text("SELECT run_id FROM audit.pipeline_runs WHERE status = 'SUCCESS' ORDER BY started_at DESC LIMIT 1")
        ).scalar_one()
        stage_names = [
            row[0]
            for row in connection.execute(
                text("SELECT stage_name FROM audit.pipeline_stage_runs WHERE run_id = :run_id ORDER BY started_at"),
                {"run_id": first_run_id},
            )
        ]
        analytics_views = {
            row[0]
            for row in connection.execute(
                text("""
                    SELECT table_name
                    FROM information_schema.views
                    WHERE (table_schema, table_name) IN (
                        ('warehouse', 'v_sales_kpi'),
                        ('warehouse', 'v_sales_monthly_kpi'),
                        ('warehouse', 'v_sales_channel_kpi'),
                        ('warehouse', 'v_top_product_kpi'),
                        ('warehouse', 'v_sales_status_kpi'),
                        ('warehouse', 'v_return_refund_kpi'),
                        ('audit', 'v_data_quality_by_rule'),
                        ('audit', 'v_data_quality_report')
                    )
                """)
            )
        }
    assert stage_names.index("raw_load") < stage_names.index("validate")
    assert stage_names.index("return_raw_load") < stage_names.index("return_staging_load")
    assert stage_names.index("return_staging_load") < stage_names.index("return_fact_load")
    assert {
        "v_sales_kpi",
        "v_sales_monthly_kpi",
        "v_sales_channel_kpi",
        "v_top_product_kpi",
        "v_sales_status_kpi",
        "v_return_refund_kpi",
        "v_data_quality_by_rule",
        "v_data_quality_report",
    } <= analytics_views

    run(source_dir)
    with engine.connect() as connection:
        second = _counts(connection)
        second_successes = connection.execute(
            text("SELECT COUNT(*) FROM audit.pipeline_runs WHERE status = 'SUCCESS'")
        ).scalar_one()
        second_metrics = connection.execute(
            text("""
            SELECT incremental_records, staged_records, fact_inserted_records
            FROM audit.pipeline_runs WHERE status = 'SUCCESS'
            ORDER BY started_at DESC LIMIT 1
        """)
        ).one()
        second_stage_names = [
            row[0]
            for row in connection.execute(
                text("""
                    SELECT stage_name
                    FROM audit.pipeline_stage_runs
                    WHERE run_id = (
                        SELECT run_id FROM audit.pipeline_runs WHERE status = 'SUCCESS'
                        ORDER BY started_at DESC LIMIT 1
                    )
                    ORDER BY started_at
                """)
            )
        ]
        duplicate_facts = connection.execute(
            text("""
            SELECT COUNT(*) FROM (
                SELECT source_name, source_order_id, source_line_number
                FROM warehouse.fact_sales
                GROUP BY source_name, source_order_id, source_line_number
                HAVING COUNT(*) > 1
            ) duplicates
        """)
        ).scalar_one()
    assert first["raw"] >= before["raw"]
    assert first["staging"] >= before["staging"]
    assert first["facts"] >= before["facts"]
    with engine.connect() as connection:
        assert connection.execute(text("SELECT COUNT(*) FROM staging.stg_returns")).scalar_one() == expected_return_rows
        assert connection.execute(text("SELECT COUNT(*) FROM warehouse.fact_returns")).scalar_one() == expected_return_rows
    assert second["raw"] == first["raw"], "unchanged source rows must not be ingested again"
    assert second["staging"] == first["staging"]
    assert second["return_staging"] == first["return_staging"]
    assert second["products"] == first["products"]
    assert second["facts"] == first["facts"]
    assert second_successes == first_successes + 1
    assert tuple(second_metrics) == (0, 0, 0)
    assert "validate" not in second_stage_names
    assert "staging_load" not in second_stage_names
    assert "fact_load" not in second_stage_names
    with engine.connect() as connection:
        report = (
            connection.execute(
                text("""
            SELECT source_records, skipped_unchanged_records, extracted_records, outcome_message, report_summary
            FROM audit.pipeline_runs WHERE status='SUCCESS' ORDER BY started_at DESC LIMIT 1
        """)
            )
            .mappings()
            .one()
        )
        assert report["source_records"] == report["skipped_unchanged_records"]
        assert report["extracted_records"] == 0
        assert "tanpa data baru atau perubahan" in report["outcome_message"]
    assert report["report_summary"]["raw"]["product_master"]["new_or_changed"] == 0
    assert duplicate_facts == 0

    # Appending catalog definitions should add only those new rows to Raw,
    # not duplicate the unchanged catalog rows from the rewritten CSV file.
    promo_path = source_dir / "promo_master.csv"
    with promo_path.open(newline="", encoding="utf-8") as file:
        promo_rows = list(csv.DictReader(file))
        promo_fields = list(promo_rows[0])
    promo_batch = uuid4().hex[:10].upper()
    for index in range(12):
        promo_rows.append({
            "promo_code": f"TEST{promo_batch}{index:02d}",
            "promo_name": f"Promo acceptance {index + 1}",
            "discount_type": "percentage",
            "discount_value": "5",
            "start_date": "2026-01-01",
            "end_date": "2026-12-31",
            "status": "active",
        })
    with promo_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=promo_fields)
        writer.writeheader()
        writer.writerows(promo_rows)
    with engine.connect() as connection:
        promo_raw_before = connection.execute(text("SELECT COUNT(*) FROM raw.promo_master")).scalar_one()
    promo_run_id = run(source_dir)
    with engine.connect() as connection:
        promo_raw_after = connection.execute(text("SELECT COUNT(*) FROM raw.promo_master")).scalar_one()
        promo_summary = connection.execute(
            text("SELECT report_summary FROM audit.pipeline_runs WHERE run_id=:run_id"),
            {"run_id": promo_run_id},
        ).scalar_one()
    promo_metrics = next(
        item for item in promo_summary["auxiliary_sources"] if item["source_name"] == "PROMO_MASTER"
    )
    assert promo_raw_after - promo_raw_before == 12
    assert promo_metrics["processed"] == promo_metrics["raw_inserted"] == 12

    _append_valid_website_rows(source_dir, 20)
    run(source_dir)
    with engine.connect() as connection:
        third = _counts(connection)
        third_successes = connection.execute(
            text("SELECT COUNT(*) FROM audit.pipeline_runs WHERE status = 'SUCCESS'")
        ).scalar_one()
    assert third["raw"] == second["raw"] + 20
    assert third["staging"] == second["staging"] + 20
    assert third["facts"] == second["facts"] + 20
    assert third["products"] == second["products"]

    order_id = f"WEB-LINES-{uuid4().hex[:12]}"
    _website_order_lines(source_dir, order_id, 5)
    inserted_run = run(source_dir)
    with engine.connect() as connection:
        first_lines = connection.execute(
            text("""SELECT source_line_number, quantity, loaded_at FROM warehouse.fact_sales
                    WHERE source_name='WEBSITE' AND source_order_id=:order_id ORDER BY source_line_number"""),
            {"order_id": order_id},
        ).all()
        raw_line = connection.execute(
            text(
                "SELECT line_item_no FROM raw.website_transactions WHERE invoice_no=:order_id ORDER BY line_item_no LIMIT 1"
            ),
            {"order_id": order_id},
        ).scalar_one()
    assert [row.source_line_number for row in first_lines] == [1, 2, 3, 4, 5]
    assert raw_line == "1"
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT fact_inserted_records, loaded_records FROM audit.pipeline_runs WHERE run_id=:run_id"),
            {"run_id": inserted_run},
        ).one() == (5, 5)
    unchanged_run = run(source_dir)
    with engine.connect() as connection:
        summary = connection.execute(text("SELECT report_summary FROM audit.pipeline_runs WHERE run_id=:id"),
                                     {"id": unchanged_run}).scalar_one()
        auxiliary = {item["source_name"]: item for item in summary["auxiliary_sources"]}
        assert set(auxiliary) == {"PROMO_MASTER", "RETURN_EVENTS"}
        assert auxiliary["RETURN_EVENTS"]["raw_inserted"] == 0
        assert auxiliary["RETURN_EVENTS"]["warehouse_written"] == 0
        assert auxiliary["PROMO_MASTER"]["file_changed"] is False
        unchanged_lines = connection.execute(
            text("""SELECT source_line_number, loaded_at FROM warehouse.fact_sales
                    WHERE source_name='WEBSITE' AND source_order_id=:order_id ORDER BY source_line_number"""),
            {"order_id": order_id},
        ).all()
    assert [row.loaded_at for row in unchanged_lines] == [row.loaded_at for row in first_lines]
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT fact_inserted_records, loaded_records FROM audit.pipeline_runs WHERE run_id=:run_id"),
            {"run_id": unchanged_run},
        ).one() == (0, 0)

    _website_order_lines(source_dir, order_id, 5, changed_line=3)
    corrected_run = run(source_dir)
    with engine.connect() as connection:
        corrected = connection.execute(
            text("""SELECT source_line_number, quantity, loaded_at FROM warehouse.fact_sales
                    WHERE source_name='WEBSITE' AND source_order_id=:order_id ORDER BY source_line_number"""),
            {"order_id": order_id},
        ).all()
    assert len(corrected) == 5
    assert corrected[2].quantity == 4
    assert corrected[2].loaded_at != first_lines[2].loaded_at
    assert all(corrected[index].loaded_at == first_lines[index].loaded_at for index in (0, 1, 3, 4))
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT fact_inserted_records, loaded_records FROM audit.pipeline_runs WHERE run_id=:run_id"),
            {"run_id": corrected_run},
        ).one() == (0, 1)

    # An invalid correction is auditable and flagged stale, while the last
    # valid fact remains unchanged until a valid source value is supplied.
    _website_order_lines(source_dir, order_id, 5, changed_line=3)
    website_path = source_dir / "website.csv"
    with website_path.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
        fields = list(rows[0])
    for row in rows:
        if row["invoice_no"] == order_id and row["line_item_no"] == "3":
            row["quantity"] = "0"
    with website_path.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    invalid_correction_run = run(source_dir)
    with engine.connect() as connection:
        stale = connection.execute(
            text("""
                SELECT source_order_id, source_line_number, rejected_run_id,
                       rejection_reason, resolved_at
                FROM audit.stale_fact_corrections
                WHERE source_name='WEBSITE' AND source_order_id=:order_id AND source_line_number=3
            """),
            {"order_id": order_id},
        ).one()
        preserved_quantity = connection.execute(
            text("""SELECT quantity FROM warehouse.fact_sales
                    WHERE source_name='WEBSITE' AND source_order_id=:order_id AND source_line_number=3"""),
            {"order_id": order_id},
        ).scalar_one()
    assert stale.source_order_id == order_id
    assert stale.source_line_number == 3
    assert stale.rejected_run_id == invalid_correction_run
    assert stale.resolved_at is None
    assert "quantity" in stale.rejection_reason.lower()
    assert preserved_quantity == 4

    # Ensure the admin operations API that feeds Settings exposes the warning.
    from dataclasses import replace

    from dashboard import routes
    from dashboard.app import app

    monkeypatch.setattr(routes, "settings", replace(routes.settings, dashboard_admin_token="integration-token"))
    operations = app.test_client().get(
        "/api/admin/operations", headers={"X-Admin-Token": "integration-token"}
    )
    assert operations.status_code == 200
    operations_payload = operations.get_json()
    assert operations_payload["stale_fact_correction_count"] >= 1
    assert any(
        item["source_order_id"] == order_id and item["source_line_number"] == 3
        for item in operations_payload["stale_fact_corrections"]
    )

    _website_order_lines(source_dir, order_id, 5, changed_line=3)
    resolution_run = run(source_dir)
    with engine.connect() as connection:
        resolved = connection.execute(
            text("""SELECT resolved_at, resolved_run_id FROM audit.stale_fact_corrections
                    WHERE source_name='WEBSITE' AND source_order_id=:order_id AND source_line_number=3"""),
            {"order_id": order_id},
        ).one()
    assert resolved.resolved_at is not None
    assert resolved.resolved_run_id == resolution_run

    _website_order_lines(source_dir, order_id, 6, changed_line=3)
    added_run = run(source_dir)
    with engine.connect() as connection:
        expanded = connection.execute(
            text("""SELECT source_line_number, loaded_at FROM warehouse.fact_sales
                    WHERE source_name='WEBSITE' AND source_order_id=:order_id ORDER BY source_line_number"""),
            {"order_id": order_id},
        ).all()
    assert [row.source_line_number for row in expanded] == [1, 2, 3, 4, 5, 6]
    assert [row.loaded_at for row in expanded[:5]] == [row.loaded_at for row in corrected]
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT fact_inserted_records, loaded_records FROM audit.pipeline_runs WHERE run_id=:run_id"),
            {"run_id": added_run},
        ).one() == (1, 1)

    _website_order_lines(source_dir, order_id, 5)
    reconciled_run = run(source_dir)
    with engine.connect() as connection:
        removed_line = connection.execute(
            text("""
                SELECT is_source_active,
                       (SELECT COUNT(*) FROM warehouse.v_sales_detail
                        WHERE source_name='WEBSITE' AND order_id=:order_id AND line_number=6) AS visible_rows
                FROM warehouse.fact_sales
                WHERE source_name='WEBSITE' AND source_order_id=:order_id AND source_line_number=6
            """),
            {"order_id": order_id},
        ).one()
        reconciliation_record = connection.execute(
            text("""
                SELECT status, observed_business_keys, deactivated_records
                FROM audit.source_reconciliations
                WHERE run_id=:run_id AND source_name='WEBSITE'
            """),
            {"run_id": reconciled_run},
        ).one()
    assert tuple(removed_line) == (False, 0)
    with (source_dir / "website.csv").open(newline="", encoding="utf-8") as stream:
        expected_keys = {
            (row["invoice_no"].strip(), int(row["line_item_no"])) for row in csv.DictReader(stream)
        }
    # Audit mencakup seluruh snapshot Website, termasuk order di luar skenario ini.
    assert tuple(reconciliation_record) == ("SUCCESS", len(expected_keys), 1)

    _website_order_lines(source_dir, order_id, 6)
    run(source_dir)
    with engine.connect() as connection:
        assert connection.execute(
            text("""
                SELECT is_source_active,
                       (SELECT COUNT(*) FROM warehouse.v_sales_detail
                        WHERE source_name='WEBSITE' AND order_id=:order_id AND line_number=6) AS visible_rows
                FROM warehouse.fact_sales
                WHERE source_name='WEBSITE' AND source_order_id=:order_id AND source_line_number=6
            """),
            {"order_id": order_id},
        ).one() == (True, 1)

    # Partial batches may omit a historical line; they must never deactivate it.
    _declare_website_snapshot(source_dir, mode="INCREMENTAL_BATCH", completeness="PARTIAL")
    _website_order_lines(source_dir, order_id, 5)
    batch_run = run(source_dir)
    with engine.connect() as connection:
        batch_line = connection.execute(
            text(
                "SELECT is_source_active FROM warehouse.fact_sales WHERE source_name='WEBSITE' AND source_order_id=:id AND source_line_number=6"
            ),
            {"id": order_id},
        ).scalar_one()
        batch_audit = connection.execute(
            text(
                "SELECT status, ingestion_mode, deactivated_records FROM audit.source_reconciliations WHERE run_id=:run_id AND source_name='WEBSITE'"
            ),
            {"run_id": batch_run},
        ).one()
    assert batch_line is True
    assert tuple(batch_audit) == ("SKIPPED", "INCREMENTAL_BATCH", 0)

    # A declared, complete empty snapshot is still reconciled on the no-op path.
    website_path = source_dir / "website.csv"
    with website_path.open(newline="", encoding="utf-8") as stream:
        website_fields = next(csv.reader(stream))
    with website_path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerow(website_fields)
    _declare_website_snapshot(source_dir, mode="FULL_SNAPSHOT", completeness="COMPLETE")
    empty_run = run(source_dir)
    with engine.connect() as connection:
        empty_audit = connection.execute(
            text(
                "SELECT status, source_records, observed_business_keys, deactivated_records FROM audit.source_reconciliations WHERE run_id=:run_id AND source_name='WEBSITE'"
            ),
            {"run_id": empty_run},
        ).one()
        historical_rows = connection.execute(
            text("SELECT COUNT(*) FROM warehouse.fact_sales WHERE source_name='WEBSITE'"),
        ).scalar_one()
        active_rows = connection.execute(
            text("SELECT COUNT(*) FROM warehouse.fact_sales WHERE source_name='WEBSITE' AND is_source_active"),
        ).scalar_one()
    assert tuple(empty_audit) == ("SUCCESS", 0, 0, historical_rows)
    assert historical_rows > 0
    assert active_rows == 0

    shutil.copy2(ROOT / "data" / "source" / "website.csv", website_path)
    _website_order_lines(source_dir, order_id, 6)
    run(source_dir)
    with engine.connect() as connection:
        assert (
            connection.execute(
                text(
                    "SELECT is_source_active FROM warehouse.fact_sales WHERE source_name='WEBSITE' AND source_order_id=:id AND source_line_number=6"
                ),
                {"id": order_id},
            ).scalar_one()
            is True
        )

    with engine.connect() as connection:
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text("""
                INSERT INTO warehouse.fact_sales
                    (source_name, source_order_id, source_line_number, date_key, product_key,
                     customer_key, channel_key, payment_key, sale_status, quantity, unit_price,
                     gross_amount, discount_amount, net_amount, source_record_hash)
                SELECT source_name, source_order_id, source_line_number, date_key, product_key,
                       customer_key, channel_key, payment_key, sale_status, quantity, unit_price,
                       gross_amount, discount_amount, net_amount, source_record_hash
                FROM warehouse.fact_sales WHERE source_name='WEBSITE' AND source_order_id=:order_id
                  AND source_line_number=1
            """),
                {"order_id": order_id},
            )
    assert third_successes == second_successes + 2  # Satu run promo incremental disisipkan di atas.

    from dashboard.app import app

    client = app.test_client()
    assert client.get("/healthz").status_code == 200
    response = client.get("/api/dashboard?start=2026-01-01&end=2026-12-31")
    assert response.status_code == 200
    payload = response.get_json()
    with engine.connect() as connection:
        expected_kpi = (
            connection.execute(
                text("""
                    SELECT COALESCE(SUM(gross_amount) FILTER (WHERE is_eligible_sale), 0) AS gross_sales,
                           COALESCE(SUM(net_amount) FILTER (WHERE is_eligible_sale), 0) AS sales_after_discount,
                           COALESCE(SUM(net_amount - processed_refund_amount)
                               FILTER (WHERE is_eligible_sale), 0) AS net_sales,
                           COUNT(DISTINCT source_name || '|' || order_id)
                               FILTER (WHERE is_eligible_sale) AS eligible_orders,
                           COALESCE(SUM(returned_units) FILTER (WHERE is_eligible_sale), 0) AS returned_units,
                           COALESCE(SUM(processed_refund_amount)
                               FILTER (WHERE is_eligible_sale), 0) AS processed_refund_amount,
                           COALESCE(ROUND(100.0 * SUM(returned_units) FILTER (WHERE is_eligible_sale)
                               / NULLIF(SUM(quantity) FILTER (WHERE is_eligible_sale), 0), 2), 0) AS return_rate
                    FROM warehouse.v_sales_detail
                    WHERE order_date BETWEEN '2026-01-01' AND '2026-12-31'
                """)
            )
            .mappings()
            .one()
        )
    assert payload["metrics"]["orders"] >= 20
    assert float(payload["metrics"]["gross_sales"]) == float(expected_kpi["gross_sales"])
    assert float(payload["metrics"]["net_sales"]) == float(expected_kpi["net_sales"])
    assert payload["metrics"]["orders"] == expected_kpi["eligible_orders"]
    assert float(payload["metrics"]["sales_after_discount"]) == float(expected_kpi["sales_after_discount"])
    assert float(payload["metrics"]["returned_units"]) == float(expected_kpi["returned_units"])
    assert float(payload["metrics"]["processed_refund_amount"]) == float(expected_kpi["processed_refund_amount"])
    assert float(payload["metrics"]["return_rate"]) == float(expected_kpi["return_rate"])
    assert {"month", "channel", "category", "city", "product", "status"} <= set(payload["charts"])

    # Alur HTTP upload -> ETL -> Warehouse: upload koreksi memperbarui diskon baris.
    from dataclasses import replace
    from io import BytesIO, StringIO

    from dashboard import routes
    from dashboard.services import ingestion

    monkeypatch.setattr(routes, "settings", replace(routes.settings, dashboard_admin_token="integration-token"))
    monkeypatch.setattr(ingestion, "SOURCE_DIR", source_dir)
    headers = {"X-Admin-Token": "integration-token"}
    for source_key in ("promo_master", "returns"):
        path = source_dir / ingestion.SOURCE_FILES[source_key]
        result = client.post("/api/ingestion/upload", headers=headers, data={
            "source": source_key, "file": (BytesIO(path.read_bytes()), path.name),
        })
        assert result.status_code == 201, result.get_json()
    run(source_dir)
    repeated = client.get("/api/dashboard?start=2026-01-01&end=2026-12-31").get_json()
    assert repeated["metrics"] == payload["metrics"]

    with (source_dir / "shopee.csv").open(newline="", encoding="utf-8") as file:
        sales_rows = list(csv.DictReader(file))
        sales_fields = list(sales_rows[0])
    corrected_sale = next(row for row in sales_rows if row["promo_code"] and row["discount_amount"] != "1.00")
    corrected_sale["discount_amount"] = "1.00"
    output = StringIO()
    writer = csv.DictWriter(output, fieldnames=sales_fields)
    writer.writeheader()
    writer.writerow(corrected_sale)
    result = client.post("/api/ingestion/upload", headers=headers, data={
        "source": "shopee", "mode": "correct",
        "file": (BytesIO(output.getvalue().encode()), "correction.csv"),
    })
    assert result.status_code == 201, result.get_json()
    run(source_dir)
    with engine.connect() as connection:
        total = connection.execute(text("""
            SELECT discount_amount FROM warehouse.fact_sales
            WHERE source_name='SHOPEE' AND source_order_id=:order_id AND source_line_number=:line
        """), {"order_id": corrected_sale["order_id"], "line": int(corrected_sale["order_line_id"])}).scalar_one()
    assert total == Decimal("1.00")

    # Small manually-calculated KPI fixture: two units, item-level discount,
    # two return events (approved + processed), a pending refund, and a cancelled order.
    day_text = "2026-12-31"  # OCTOBER8 promo is valid through this date.
    baseline = client.get(f"/api/dashboard?start={day_text}&end={day_text}").get_json()["metrics"]
    kpi_order_id = f"WEB-KPI-{uuid4().hex[:10]}"
    cancelled_order_id = f"WEB-KPI-CANCEL-{uuid4().hex[:10]}"
    with (source_dir / "website.csv").open(newline="", encoding="utf-8") as file:
        website_rows = list(csv.DictReader(file))
        website_fields = list(website_rows[0])
    template = next(row for row in website_rows if row["status"] == "completed")
    kpi_sale = dict(template)
    kpi_sale.update({
        "invoice_no": kpi_order_id, "line_item_no": "1", "created_at": f"{day_text}T12:00:00",
        "quantity": "2", "discount_amount": "10.00", "promo_code": "OCTOBER8", "status": "completed",
    })
    kpi_sale["total_amount"] = str(
        (Decimal(kpi_sale["unit_price"]) * 2 - Decimal("10.00")).quantize(Decimal("0.01"))
    )
    cancelled_sale = dict(kpi_sale)
    cancelled_sale.update({
        "invoice_no": cancelled_order_id, "quantity": "1", "discount_amount": "0.00",
        "promo_code": "", "status": "cancelled",
    })
    cancelled_sale["total_amount"] = cancelled_sale["unit_price"]
    website_rows.extend((kpi_sale, cancelled_sale))
    with (source_dir / "website.csv").open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=website_fields)
        writer.writeheader()
        writer.writerows(website_rows)

    return_path = source_dir / "return_refund.csv"
    with return_path.open(newline="", encoding="utf-8") as file:
        return_rows = list(csv.DictReader(file))
        return_fields = list(return_rows[0])
    for return_id, status, quantity, refund, refund_status in (
        (f"RET-KPI-PROCESSED-{uuid4().hex[:8]}", "PROCESSED", "1", "25.00", "PROCESSED"),
        (f"RET-KPI-APPROVED-{uuid4().hex[:8]}", "APPROVED", "1", "", "PENDING"),
    ):
        return_rows.append({
            "source_name": "WEBSITE", "return_id": return_id, "return_line_number": "1",
            "order_id": kpi_order_id, "order_line_number": "1", "return_date": day_text,
            "return_reason": "Uji KPI acceptance", "return_status": status,
            "quantity_returned": quantity, "refund_amount": refund, "refund_status": refund_status,
        })
    with return_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=return_fields)
        writer.writeheader()
        writer.writerows(return_rows)

    run(source_dir)
    kpi_response = client.get(f"/api/dashboard?start={day_text}&end={day_text}")
    assert kpi_response.status_code == 200
    actual = kpi_response.get_json()["metrics"]
    gross = Decimal(kpi_sale["unit_price"]) * 2
    expected = {
        "gross_sales": gross,
        "discount_total": Decimal("10.00"),
        "sales_after_discount": gross - Decimal("10.00"),
        "processed_refund_amount": Decimal("25.00"),
        "net_sales": gross - Decimal("35.00"),
        "orders": 1,
        "gross_order_value_all_statuses": gross + Decimal(kpi_sale["unit_price"]),
        "units": 2,
        "returned_units": 2,
    }
    for field, value in expected.items():
        assert float(actual[field]) - float(baseline[field]) == float(value), (
            field, actual[field], baseline[field], value
        )
    expected_return_rate = round(
        100 * (float(baseline["returned_units"]) + 2) / (float(baseline["units"]) + 2), 2
    )
    assert actual["return_rate"] == expected_return_rate

    # An invalid correction to an existing return event preserves the last
    # valid warehouse row, exposes a stale warning, and resolves when the
    # original valid event is supplied again (even with an identical hash).
    return_path = source_dir / "return_refund.csv"
    with return_path.open(newline="", encoding="utf-8") as file:
        return_rows = list(csv.DictReader(file))
        return_fields = list(return_rows[0])
    corrected_return = next(row for row in return_rows if row["source_name"] == "SHOPEE")
    event_id = corrected_return["return_id"]
    event_line = int(corrected_return["return_line_number"])
    original_return_date = corrected_return["return_date"]
    with engine.connect() as connection:
        original_fact_date = connection.execute(text("""
            SELECT return_date FROM warehouse.fact_returns
            WHERE source_name='SHOPEE' AND return_id=:return_id AND return_line_number=:line
        """), {"return_id": event_id, "line": event_line}).scalar_one()
    corrected_return["return_date"] = "not-a-date"
    with return_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=return_fields)
        writer.writeheader()
        writer.writerows(return_rows)
    with engine.connect() as connection:
        promo_state_before = connection.execute(text("""
            SELECT COUNT(*) FILTER (WHERE is_active), COUNT(*)
            FROM warehouse.dim_promotion
        """)).one()
    invalid_return_run = run(source_dir)
    with engine.connect() as connection:
        stale_return = connection.execute(text("""
            SELECT source_order_id, source_line_number, rejected_run_id, rejection_reason, resolved_at
            FROM audit.stale_fact_corrections
            WHERE source_name='RETURN_EVENTS'
              AND source_order_id=:business_key AND source_line_number=:line
        """), {"business_key": f"SHOPEE:{event_id}", "line": event_line}).one()
        preserved_return_date = connection.execute(text("""
            SELECT return_date FROM warehouse.fact_returns
            WHERE source_name='SHOPEE' AND return_id=:return_id AND return_line_number=:line
        """), {"return_id": event_id, "line": event_line}).scalar_one()
        promo_state = connection.execute(text("""
            SELECT COUNT(*) FILTER (WHERE is_active), COUNT(*)
            FROM warehouse.dim_promotion
        """)).one()
        invalid_run_summary = connection.execute(text("""
            SELECT report_summary FROM audit.pipeline_runs WHERE run_id=:run_id
        """), {"run_id": invalid_return_run}).scalar_one()
    assert stale_return.rejected_run_id == invalid_return_run
    assert stale_return.resolved_at is None
    assert "return_date" in stale_return.rejection_reason
    assert preserved_return_date == original_fact_date
    assert promo_state == promo_state_before
    assert invalid_run_summary["dimensions"]["promotions_processed"] == 0

    operations_payload = client.get("/api/admin/operations", headers=headers).get_json()
    assert operations_payload["stale_fact_correction_count"] >= 1
    visible_return = next(
        item for item in operations_payload["stale_fact_corrections"]
        if item["record_type"] == "RETURN" and item["source_order_id"] == event_id
    )
    assert visible_return["source_name"] == "Return / SHOPEE"

    corrected_return["return_date"] = original_return_date
    with return_path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=return_fields)
        writer.writeheader()
        writer.writerows(return_rows)
    from pipeline.returns import extract_return_events, filter_unseen_return_rows

    with engine.connect() as connection:
        source_snapshot = connection.execute(text("""
            SELECT payload_hashes FROM audit.source_snapshots
            WHERE pipeline_name='ecommerce_sales_pipeline' AND source_name='RETURN_EVENTS'
        """)).scalar_one()
    retry_source = extract_return_events(source_dir)
    retry_delta = filter_unseen_return_rows(
        retry_source, set(source_snapshot), {("SHOPEE", event_id, event_line)}
    )
    assert event_id in set(retry_delta.frame["return_id"].astype(str))
    resolved_return_run = run(source_dir)
    with engine.connect() as connection:
        resolved_return = connection.execute(text("""
            SELECT resolved_at, resolved_run_id FROM audit.stale_fact_corrections
            WHERE source_name='RETURN_EVENTS'
              AND source_order_id=:business_key AND source_line_number=:line
        """), {"business_key": f"SHOPEE:{event_id}", "line": event_line}).one()
    assert resolved_return.resolved_at is not None
    assert resolved_return.resolved_run_id == resolved_return_run

    # Exercise the real dashboard worker launcher against this isolated DB,
    # then run the same source snapshot through Airflow's shared runner task.
    dashboard_run = client.post("/api/pipeline/run", headers=headers)
    assert dashboard_run.status_code == 202, dashboard_run.get_json()
    dashboard_run_id = dashboard_run.get_json()["run_id"]
    deadline = time.monotonic() + 90
    dashboard_result = None
    while time.monotonic() < deadline:
        progress = client.get(
            f"/api/pipeline/progress?run_id={dashboard_run_id}", headers=headers
        )
        assert progress.status_code == 200, progress.get_json()
        dashboard_result = progress.get_json()["run"]
        if dashboard_result["status"] in {"SUCCESS", "FAILED", "PARTIAL_SUCCESS"}:
            break
        time.sleep(0.25)
    assert dashboard_result is not None
    assert dashboard_result["status"] == "SUCCESS", dashboard_result

    # Airflow is supported through its Linux container runtime; local Windows
    # Python has no supported Airflow SDK import path.
    if os.name != "nt":
        from airflow.orchestration import run_pipeline_task

        airflow_run_id = run_pipeline_task(
            ti=SimpleNamespace(run_id="manual__isolated_acceptance"),
            run_id="manual__isolated_acceptance",
        )
        with engine.connect() as connection:
            airflow_run = connection.execute(
                text("SELECT status, extracted_records, orchestration_run_id FROM audit.pipeline_runs WHERE run_id=:id"),
                {"id": airflow_run_id},
            ).one()
        assert tuple(airflow_run) == ("SUCCESS", 0, "manual__isolated_acceptance")
