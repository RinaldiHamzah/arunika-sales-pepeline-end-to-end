"""Acceptance tests against a disposable PostgreSQL database.

Run explicitly with ``RUN_POSTGRES_TESTS=1`` after the schema has been loaded.
The test executes the real runner three times and verifies the published API.
"""
import csv
import os
import shutil
from pathlib import Path

import pytest
from sqlalchemy import text

from pipeline.database import get_engine
from pipeline.runner import run


pytestmark = pytest.mark.integration
ROOT = Path(__file__).resolve().parents[1]


def _enabled():
    return os.getenv("RUN_POSTGRES_TESTS", "0") == "1"


def _counts(connection):
    return {
        "raw": sum(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()
                   for table in ("raw.shopee_orders", "raw.tokopedia_transactions",
                                 "raw.website_transactions", "raw.offline_store_sales",
                                 "raw.product_master")),
        "staging": connection.execute(text("SELECT COUNT(*) FROM staging.stg_sales")).scalar_one(),
        "products": connection.execute(text("SELECT COUNT(*) FROM warehouse.dim_product")).scalar_one(),
        "facts": connection.execute(text("SELECT COUNT(*) FROM warehouse.fact_sales")).scalar_one(),
    }


def _append_valid_website_rows(source_dir, count=20):
    path = Path(source_dir) / "website.csv"
    with path.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
        fields = rows[0].keys()
    template = next(row for row in rows if row["status"] == "completed")
    for index in range(count):
        row = dict(template)
        row["invoice_no"] = f"WEB-NEW-{index:04d}"
        rows.append(row)
    with path.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


@pytest.mark.skipif(not _enabled(), reason="set RUN_POSTGRES_TESTS=1 to run PostgreSQL integration tests")
def test_full_pipeline_and_incremental_acceptance(tmp_path):
    source_dir = tmp_path / "source"
    source_dir.mkdir()
    for name in ("product.csv", "shopee.csv", "tokopedia.csv", "website.csv", "offline.csv"):
        shutil.copy2(ROOT / "data" / "source" / name, source_dir / name)

    engine = get_engine()
    with engine.connect() as connection:
        before = _counts(connection)
        required = connection.execute(text("""
            SELECT COUNT(*) FROM information_schema.tables
            WHERE (table_schema, table_name) IN
              (('raw', 'shopee_orders'), ('staging', 'stg_sales'),
               ('warehouse', 'fact_sales'), ('warehouse', 'dim_product'),
               ('audit', 'pipeline_runs'))
        """)).scalar_one()
        if required != 5:
            pytest.fail("Database schema is not initialized; load database/schema/*.sql first")

    run(source_dir)
    with engine.connect() as connection:
        first = _counts(connection)
        first_successes = connection.execute(text(
            "SELECT COUNT(*) FROM audit.pipeline_runs WHERE status = 'SUCCESS'"
        )).scalar_one()

    run(source_dir)
    with engine.connect() as connection:
        second = _counts(connection)
        second_successes = connection.execute(text(
            "SELECT COUNT(*) FROM audit.pipeline_runs WHERE status = 'SUCCESS'"
        )).scalar_one()
        second_metrics = connection.execute(text("""
            SELECT incremental_records, staged_records, fact_inserted_records
            FROM audit.pipeline_runs WHERE status = 'SUCCESS'
            ORDER BY started_at DESC LIMIT 1
        """)).one()
        duplicate_facts = connection.execute(text("""
            SELECT COUNT(*) FROM (
                SELECT source_name, source_order_id, source_line_number
                FROM warehouse.fact_sales
                GROUP BY source_name, source_order_id, source_line_number
                HAVING COUNT(*) > 1
            ) duplicates
        """)).scalar_one()
    assert first["raw"] >= before["raw"]
    assert first["staging"] >= before["staging"]
    assert first["facts"] >= before["facts"]
    assert second == first, "unchanged snapshot inserted new records"
    assert second_successes == first_successes + 1
    assert tuple(second_metrics) == (0, 0, 0)
    assert duplicate_facts == 0

    _append_valid_website_rows(source_dir, 20)
    run(source_dir)
    with engine.connect() as connection:
        third = _counts(connection)
        third_successes = connection.execute(text(
            "SELECT COUNT(*) FROM audit.pipeline_runs WHERE status = 'SUCCESS'"
        )).scalar_one()
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
    assert payload["metrics"]["orders"] >= 20
    assert {"month", "channel", "category", "city", "product", "status"} <= set(payload["charts"])
