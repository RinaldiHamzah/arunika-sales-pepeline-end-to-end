"""Acceptance tests against an isolated PostgreSQL database.

The test is intentionally blocked unless its dedicated test-database markers
are present. It executes the real runner three times and must never target a
developer or production warehouse.
"""

import csv
import os
import shutil
import tempfile
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text

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
        "products": connection.execute(text("SELECT COUNT(*) FROM warehouse.dim_product")).scalar_one(),
        "facts": connection.execute(text("SELECT COUNT(*) FROM warehouse.fact_sales")).scalar_one(),
    }


def _reset_isolated_database(engine) -> None:
    """Clear only the explicitly marked acceptance-test database.

    Docker may retain the test container between runs. Resetting every project
    table makes the first run deterministic while Alembic keeps the schema and
    migration version intact.
    """
    assert _enabled(), "The destructive test reset requires the isolated database markers."
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
        # A unique business key keeps the test repeatable against a persistent
        # developer database where a previous acceptance run may still exist.
        row["invoice_no"] = f"WEB-TEST-{test_batch}-{index:04d}"
        rows.append(row)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _source_row_count(source_dir):
    return sum(
        len(list(csv.DictReader((Path(source_dir) / name).open(encoding="utf-8", newline=""))))
        for name in ("product.csv", "shopee.csv", "tokopedia.csv", "website.csv", "offline.csv")
    )


@pytest.mark.skipif(
    not _enabled(),
    reason="run against the isolated ecommerce_sales_test database via the test compose profile",
)
def test_full_pipeline_and_incremental_acceptance():
    # pytest's ``tmp_path`` and a repository folder can be locked by OneDrive
    # on Windows. Use a dedicated directory in the OS temporary area instead.
    runtime_root = Path(os.getenv("ARUNIKA_TEST_RUNTIME", str(Path(tempfile.gettempdir()) / "arunika_ecommerce_tests")))
    runtime_root.mkdir(exist_ok=True)
    source_dir = Path(tempfile.mkdtemp(dir=runtime_root)) / "source"
    source_dir.mkdir()
    for name in ("product.csv", "shopee.csv", "tokopedia.csv", "website.csv", "offline.csv"):
        shutil.copy2(ROOT / "data" / "source" / name, source_dir / name)
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
               ('audit', 'pipeline_runs'))
        """)
        ).scalar_one()
        if required != 5:
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
                        ('audit', 'v_data_quality_by_rule'),
                        ('audit', 'v_data_quality_report')
                    )
                """)
            )
        }
    assert stage_names.index("raw_load") < stage_names.index("validate")
    assert {
        "v_sales_kpi",
        "v_sales_monthly_kpi",
        "v_sales_channel_kpi",
        "v_top_product_kpi",
        "v_sales_status_kpi",
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
    assert second["raw"] == first["raw"], "unchanged source rows must not be ingested again"
    assert second["staging"] == first["staging"]
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
    assert third_successes == second_successes + 1

    from dashboard.flask import app

    client = app.test_client()
    assert client.get("/healthz").status_code == 200
    response = client.get("/api/dashboard?start=2026-01-01&end=2026-12-31")
    assert response.status_code == 200
    payload = response.get_json()
    with engine.connect() as connection:
        expected_kpi = (
            connection.execute(
                text("""
                    SELECT COALESCE(SUM(gross_amount), 0) AS gross_sales,
                           COALESCE(SUM(net_amount) FILTER (WHERE status = 'COMPLETED'), 0) AS net_sales,
                           COUNT(DISTINCT source_name || '|' || order_id)
                               FILTER (WHERE status = 'COMPLETED') AS completed_orders
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
    assert payload["metrics"]["orders"] == expected_kpi["completed_orders"]
    assert {"month", "channel", "category", "city", "product", "status"} <= set(payload["charts"])
