"""Fail-fast checks for the published PostgreSQL warehouse."""

from __future__ import annotations

import sys
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from pipeline.database import get_engine


def validate_warehouse(run_id=None) -> None:
    """Validate the latest successful run and core warehouse invariants."""
    with get_engine().begin() as connection:
        run = (
            connection.execute(
                text("""
            SELECT status, valid_records, invalid_records, loaded_records
            FROM audit.pipeline_runs
            WHERE status = 'SUCCESS' AND (CAST(:run_id AS UUID) IS NULL OR run_id=CAST(:run_id AS UUID))
            ORDER BY started_at DESC
            LIMIT 1
        """),
                {"run_id": run_id},
            )
            .mappings()
            .one_or_none()
        )
        if run is None:
            raise RuntimeError("No successful pipeline run found")
        fact_count = connection.execute(text("SELECT COUNT(*) FROM warehouse.fact_sales")).scalar_one()
        duplicate_facts = connection.execute(
            text("""
            SELECT COUNT(*) FROM (
                SELECT source_name, source_order_id, source_line_number
                FROM warehouse.fact_sales
                GROUP BY source_name, source_order_id, source_line_number
                HAVING COUNT(*) > 1
            ) duplicate_keys
        """)
        ).scalar_one()
        view_count = connection.execute(text("SELECT COUNT(*) FROM warehouse.v_sales_detail")).scalar_one()
        if fact_count != view_count:
            raise RuntimeError(f"Fact/view count mismatch: {fact_count} != {view_count}")
        if duplicate_facts:
            raise RuntimeError(f"Duplicate fact business keys: {duplicate_facts}")
        if int(run["loaded_records"]) > fact_count:
            raise RuntimeError("Latest loaded count exceeds current fact count")
        print({"latest_run": dict(run), "fact_count": fact_count, "view_count": view_count})


if __name__ == "__main__":
    validate_warehouse()
