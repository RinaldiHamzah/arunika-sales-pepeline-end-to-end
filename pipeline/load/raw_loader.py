"""Load extracted records, unchanged, into raw PostgreSQL tables."""
from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from pipeline.extract.base import ExtractedSource


def load_raw(connection: Connection, run_id: UUID, source: ExtractedSource) -> int:
    missing = set(source.column_mapping) - set(source.frame.columns)
    if missing:
        raise ValueError(f"{source.source_name} is missing expected columns: {sorted(missing)}")

    columns = ["ingestion_run_id", "source_file_name", "source_row_number", *source.column_mapping.values(), "source_payload"]
    placeholders = [":ingestion_run_id", ":source_file_name", ":source_row_number", *[f":{column}" for column in source.column_mapping.values()], "CAST(:source_payload AS JSONB)"]
    statement = text(f"INSERT INTO {source.raw_table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)}) ON CONFLICT DO NOTHING")
    existing_rows = {
        row[0]
        for row in connection.execute(
            text(f"SELECT source_row_number FROM {source.raw_table} WHERE source_file_name = :file_name"),
            {"file_name": source.file_path.name},
        )
    }
    records = []
    for source_row_number, row in enumerate(source.frame.to_dict(orient="records"), start=1):
        if source_row_number in existing_rows:
            continue
        record = {target: "" if row.get(input_name) is None else str(row.get(input_name, "")) for input_name, target in source.column_mapping.items()}
        record.update({
            "ingestion_run_id": str(run_id),
            "source_file_name": source.file_path.name,
            "source_row_number": source_row_number,
            "source_payload": json.dumps(row, default=str, ensure_ascii=False),
        })
        records.append(record)
    if records:
        connection.execute(statement, records)
    connection.execute(text("""
        INSERT INTO audit.source_ingestions
            (run_id, source_name, source_file_name, source_file_path, file_checksum_sha256, source_format, extracted_records)
        VALUES (:run_id, :source_name, :file_name, :file_path, :checksum, :source_format, :records)
        ON CONFLICT (run_id, source_name, file_checksum_sha256) DO NOTHING
    """), {"run_id": str(run_id), "source_name": source.source_name, "file_name": source.file_path.name,
             "file_path": str(source.file_path.resolve()), "checksum": source.checksum_sha256,
             "source_format": source.source_format, "records": len(records)})
    return len(records)
