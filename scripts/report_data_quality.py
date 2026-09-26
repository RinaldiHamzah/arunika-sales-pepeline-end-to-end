"""Print the latest or selected data-quality evidence from PostgreSQL."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
if __package__ is None and str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline.database import get_engine  # noqa: E402


def report_data_quality(run_id: str | None = None) -> dict:
    """Return a per-source quality summary and its auditable rule details."""
    with get_engine().connect() as connection:
        selected_run_id = (
            run_id
            or connection.execute(
                text("""
                SELECT run_id
                FROM audit.pipeline_runs
                ORDER BY started_at DESC
                LIMIT 1
            """)
            ).scalar_one_or_none()
        )
        if selected_run_id is None:
            return {"run": None, "sources": [], "rules": []}
        run = (
            connection.execute(
                text("""
                SELECT run_id, pipeline_name, status, started_at, ended_at,
                       source_records, extracted_records, validated_records,
                       rejected_records, duplicate_records
                FROM audit.pipeline_runs
                WHERE run_id = CAST(:run_id AS UUID)
            """),
                {"run_id": str(selected_run_id)},
            )
            .mappings()
            .one()
        )
        sources = (
            connection.execute(
                text("""
                SELECT source_name, source_records, candidate_records,
                       skipped_unchanged_records, valid_records, rejected_records,
                       duplicate_records, missing_value_records, duplicate_issue_records,
                       invalid_quantity_records, invalid_price_or_amount_records,
                       invalid_date_records, invalid_status_records,
                       unmapped_product_records, other_issue_records, warning_issue_records
                FROM audit.v_data_quality_report
                WHERE run_id = CAST(:run_id AS UUID)
                ORDER BY source_name
            """),
                {"run_id": str(selected_run_id)},
            )
            .mappings()
            .all()
        )
        rules = (
            connection.execute(
                text("""
                SELECT source_name, rule_name, severity, failed_records, details
                FROM audit.v_data_quality_by_rule
                WHERE run_id = CAST(:run_id AS UUID)
                ORDER BY source_name, severity DESC, rule_name
            """),
                {"run_id": str(selected_run_id)},
            )
            .mappings()
            .all()
        )
    return {
        "run": dict(run),
        "sources": [dict(row) for row in sources],
        "rules": [dict(row) for row in rules],
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Show data-quality evidence for a pipeline run.")
    parser.add_argument("--run-id", help="UUID run pipeline; default adalah run terbaru.")
    args = parser.parse_args()
    print(json.dumps(report_data_quality(args.run_id), default=str, ensure_ascii=False, indent=2))
