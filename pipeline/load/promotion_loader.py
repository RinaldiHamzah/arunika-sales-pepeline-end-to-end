"""Pemuatan Raw promo dan dimensi promo."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from pipeline.extract.base import ExtractedSource


def load_promotion_raw(connection: Connection, run_id: UUID, sources: list[ExtractedSource]) -> int:
    """Simpan versi sumber promo yang berubah sebagai bukti Raw append-only."""
    count = 0
    for source in sources:
        table = source.raw_table
        columns = list(source.column_mapping.values())
        names = ["ingestion_run_id", "source_file_name", "source_row_number", *columns, "source_payload"]
        values = [":ingestion_run_id", ":source_file_name", ":source_row_number"]
        values.extend(f":{column}" for column in columns)
        values.append("CAST(:source_payload AS JSONB)")
        statement = text(f"INSERT INTO {table} ({', '.join(names)}) VALUES ({', '.join(values)})")
        records = []
        for row_number, row in zip(source.row_numbers, source.frame.to_dict("records")):
            record = {
                "ingestion_run_id": str(run_id),
                "source_file_name": source.file_path.name,
                "source_row_number": row_number,
                "source_payload": json.dumps(row, default=str, ensure_ascii=False),
            }
            record.update({column: "" if row.get(column) is None else str(row[column]) for column in columns})
            records.append(record)
        if records:
            connection.execute(statement, records)
        connection.execute(
            text("""
                INSERT INTO audit.source_ingestions
                    (run_id, source_name, source_file_name, source_file_path,
                     file_checksum_sha256, source_format, extracted_records)
                VALUES (:run_id, :source_name, :file_name, :file_path,
                        :checksum, 'CSV', :records)
            """),
            {
                "run_id": str(run_id),
                "source_name": source.source_name,
                "file_name": source.file_path.name,
                "file_path": str(source.file_path.resolve()),
                "checksum": source.checksum_sha256,
                "records": len(records),
            },
        )
        count += len(records)
    return count


def load_promotion_dimension(connection: Connection, promotions: dict[str, dict]) -> int:
    """Sinkronkan definisi promo aktif; nominal aktual tetap berasal dari redemption."""
    connection.execute(text("UPDATE warehouse.dim_promotion SET is_active = FALSE"))
    rows = [
        {
            "promo_code": row["promo_code"],
            "promo_name": row["promo_name"],
            "discount_type": row["discount_type"],
            "discount_value": row["discount_value"],
            "start_date": row["start_date"],
            "end_date": row["end_date"],
            "status": row["status"],
        }
        for row in promotions.values()
    ]
    if rows:
        connection.execute(
            text("""
                INSERT INTO warehouse.dim_promotion
                    (promo_code, promo_name, discount_type, discount_value,
                     start_date, end_date, status, is_active)
                VALUES
                    (:promo_code, :promo_name, :discount_type, :discount_value,
                     :start_date, :end_date, :status, TRUE)
                ON CONFLICT (promo_code) DO UPDATE SET
                    promo_name = EXCLUDED.promo_name,
                    discount_type = EXCLUDED.discount_type,
                    discount_value = EXCLUDED.discount_value,
                    start_date = EXCLUDED.start_date,
                    end_date = EXCLUDED.end_date,
                    status = EXCLUDED.status,
                    is_active = TRUE,
                    updated_at = CURRENT_TIMESTAMP
            """),
            rows,
        )
    return len(rows)
