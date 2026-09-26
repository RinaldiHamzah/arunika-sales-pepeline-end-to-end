"""Persist data-quality evidence and run watermarks in PostgreSQL."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from pipeline.transform.standardize import SOURCE_NAMES


def _quality_category(rule: object, field: object) -> str:
    """Classify a finding so the report can show business-relevant totals."""
    rule_name = str(rule)
    field_name = str(field).lower()
    if rule_name in {"MISSING_REQUIRED", "MISSING_OPTIONAL"}:
        return "missing_value"
    if rule_name in {"DUPLICATE_BUSINESS_KEY", "CONFLICTING_DUPLICATE"}:
        return "duplicate"
    if rule_name == "INVALID_DATE":
        return "invalid_date"
    if rule_name == "INVALID_STATUS":
        return "invalid_status"
    if rule_name == "UNMAPPED_PRODUCT":
        return "unmapped_product"
    if field_name in {"qty", "quantity", "units"}:
        return "invalid_quantity"
    if field_name in {"price", "unit_price", "item_price", "total_amount"}:
        return "invalid_price_or_amount"
    return "other"


def load_stage_runs(connection, run_id: UUID, stages) -> None:
    """Persist per-stage timings collected by the runner."""
    if not stages:
        return
    connection.execute(
        text("""
        INSERT INTO audit.pipeline_stage_runs
            (run_id, stage_name, status, started_at, ended_at, duration_seconds,
             records_processed, error_message)
        VALUES (:run_id, :stage_name, :status, :started_at, :ended_at,
                :duration_seconds, :records_processed, :error_message)
    """),
        [{**stage, "run_id": str(run_id)} for stage in stages],
    )


def load_quality_audit(connection: Connection, run_id: UUID, results) -> None:
    """Persist rule counts and rejected records for one pipeline run."""
    quality_rows = []
    rejected_rows = []
    for source, result in results.items():
        source_name = "PRODUCT_MASTER" if source == "product" else SOURCE_NAMES[source]
        issues = result.issues
        if not issues.empty:
            grouped = (
                issues.groupby(["rule", "severity", "field"], dropna=False).size().reset_index(name="failed_records")
            )
            for row in grouped.to_dict("records"):
                field = str(row["field"])
                quality_rows.append(
                    {
                        "run_id": str(run_id),
                        "source_name": source_name,
                        "rule_name": str(row["rule"]),
                        "severity": str(row["severity"]),
                        "failed_records": int(row["failed_records"]),
                        "details": json.dumps(
                            {
                                "field": field,
                                "category": _quality_category(row["rule"], field),
                                "field_count": int(row["failed_records"]),
                            }
                        ),
                    }
                )
        for record in result.rejected.to_dict("records"):
            payload = record.get("raw_payload") or "{}"
            rejected_rows.append(
                {
                    "run_id": str(run_id),
                    "source_name": source_name,
                    "source_order_id": record.get("business_key"),
                    "source_row_number": record.get("source_row_number"),
                    "rejection_reason": record.get("reasons") or "REJECTED",
                    "source_payload": payload,
                }
            )
    if quality_rows:
        connection.execute(
            text("""
            INSERT INTO audit.data_quality_results
                (run_id, source_name, rule_name, severity, failed_records, details)
            VALUES
                (:run_id, :source_name, :rule_name, :severity, :failed_records,
                 CAST(:details AS JSONB))
        """),
            quality_rows,
        )
    if rejected_rows:
        connection.execute(
            text("""
            INSERT INTO audit.rejected_records
                (run_id, source_name, source_order_id, source_row_number,
                 rejection_reason, source_payload)
            VALUES
                (:run_id, :source_name, :source_order_id, :source_row_number,
                 :rejection_reason, CAST(:source_payload AS JSONB))
        """),
            rejected_rows,
        )


def update_watermarks(connection: Connection, run_id: UUID, results) -> None:
    """Advance each source watermark only after its run succeeds."""
    rows = []
    for source, result in results.items():
        source_name = "PRODUCT_MASTER" if source == "product" else SOURCE_NAMES[source]
        rows.append(
            {
                "pipeline_name": "ecommerce_sales_pipeline",
                "source_name": source_name,
                "run_id": str(run_id),
                "last_business_key": str(result.summary["valid_records"]),
            }
        )
    connection.execute(
        text("""
        INSERT INTO audit.pipeline_watermarks
            (pipeline_name, source_name, last_successful_run_id, last_processed_at, last_business_key)
        VALUES (:pipeline_name, :source_name, :run_id, CURRENT_TIMESTAMP, :last_business_key)
        ON CONFLICT (pipeline_name, source_name) DO UPDATE SET
            last_successful_run_id = EXCLUDED.last_successful_run_id,
            last_processed_at = EXCLUDED.last_processed_at,
            last_business_key = EXCLUDED.last_business_key,
            updated_at = CURRENT_TIMESTAMP
    """),
        rows,
    )
