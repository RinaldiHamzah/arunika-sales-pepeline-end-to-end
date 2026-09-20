"""Display the latest Arunika pipeline performance from the audit database.

Examples:
    python scripts/monitor_pipeline.py
    python scripts/monitor_pipeline.py --follow 10
"""

from __future__ import annotations

import argparse
import json
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

if __package__ is None:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from pipeline.database import get_engine


def _json_value(value):
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if value.__class__.__name__ == "UUID":
        return str(value)
    return value


def _row(row):
    return {key: _json_value(value) for key, value in row.items()}


def collect_performance(run_id: str | None = None) -> dict:
    """Return an operational snapshot for one run or the latest run."""
    with get_engine().connect() as connection:
        run_query = """
                SELECT run_id, pipeline_name, started_at, ended_at, status,
                       extracted_records, valid_records, duplicate_records,
                       invalid_records, loaded_records, validated_records,
                       rejected_records, incremental_records, staged_records,
                       dimension_records, fact_inserted_records,
                       fact_skipped_records, duration_seconds, error_message
                FROM audit.pipeline_runs
        """
        params = {}
        if run_id:
            run_query += " WHERE run_id = CAST(:run_id AS UUID)"
            params["run_id"] = run_id
        run_query += " ORDER BY started_at DESC LIMIT 1"
        run = connection.execute(text(run_query), params).mappings().one_or_none()
        if run is None:
            return {"status": "NO_RUN", "message": "Belum ada pipeline run pada audit database."}

        selected_run_id = str(run["run_id"])
        stages = connection.execute(
            text("""
                SELECT stage_name, status, started_at, ended_at,
                       duration_seconds, records_processed, error_message
                FROM audit.pipeline_stage_runs
                WHERE run_id = :run_id
                ORDER BY started_at
            """),
            {"run_id": selected_run_id},
        ).mappings().all()
        quality = connection.execute(
            text("""
                SELECT source_name, rule_name, severity, failed_records, details
                FROM audit.data_quality_results
                WHERE run_id = :run_id
                ORDER BY failed_records DESC, source_name, rule_name
            """),
            {"run_id": selected_run_id},
        ).mappings().all()
        freshness = connection.execute(
            text("""
                SELECT source_name, source_file_name, file_checksum_sha256,
                       extracted_records, extracted_at
                FROM audit.source_ingestions
                WHERE run_id = :run_id
                ORDER BY source_name
            """),
            {"run_id": selected_run_id},
        ).mappings().all()

    payload = _row(run)
    payload["stages"] = [_row(item) for item in stages]
    payload["quality_issues"] = [_row(item) for item in quality]
    payload["source_freshness"] = [_row(item) for item in freshness]
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Monitor Arunika pipeline performance from PostgreSQL audit tables.")
    parser.add_argument("--run-id", help="Audit pipeline UUID to inspect instead of the latest run.")
    parser.add_argument("--follow", type=int, metavar="SECONDS", help="Refresh continuously every N seconds.")
    args = parser.parse_args()

    while True:
        print(json.dumps(collect_performance(args.run_id), indent=2, ensure_ascii=False))
        if not args.follow or args.follow < 1:
            break
        time.sleep(args.follow)


if __name__ == "__main__":
    main()
