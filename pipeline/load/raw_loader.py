"""Load extracted records, unchanged, into raw PostgreSQL tables."""

from __future__ import annotations

import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from pipeline.config import settings
from pipeline.extract.base import ExtractedSource, raw_payload_hash


def load_source_snapshots(connection):
    return {
        row["source_name"]: dict(row)
        for row in connection.execute(
            text("""
            SELECT source_name, file_checksum_sha256, payload_hashes, source_records
            FROM audit.source_snapshots WHERE pipeline_name=:name
        """),
            {"name": settings.pipeline_name},
        ).mappings()
    }


def existing_raw_hashes(connection: Connection, sources: list[ExtractedSource]) -> dict[str, set[str]]:
    """Only the last successful snapshot, never the historical union."""
    snapshots = load_source_snapshots(connection)
    return {
        source.source_name: set(snapshots.get(source.source_name, {}).get("payload_hashes", [])) for source in sources
    }


def save_source_snapshots(connection, run_id, sources, previous):
    for source in sources:
        old = previous.get(source.source_name, {})
        hashes = (
            old.get("payload_hashes", [])
            if old.get("file_checksum_sha256") == source.checksum_sha256
            else [raw_payload_hash(row) for row in source.frame.to_dict("records")]
        )
        connection.execute(
            text("""
            INSERT INTO audit.source_snapshots
                (pipeline_name, source_name, file_checksum_sha256, payload_hashes, run_id, source_records)
            VALUES (:name, :source, :checksum, CAST(:hashes AS JSONB), :run_id, :source_records)
            ON CONFLICT (pipeline_name, source_name) DO UPDATE SET
                file_checksum_sha256=EXCLUDED.file_checksum_sha256,
                payload_hashes=EXCLUDED.payload_hashes, run_id=EXCLUDED.run_id,
                source_records=EXCLUDED.source_records,
                updated_at=CURRENT_TIMESTAMP
        """),
            {
                "name": settings.pipeline_name,
                "source": source.source_name,
                "checksum": source.checksum_sha256,
                "hashes": json.dumps(sorted(set(hashes))),
                "run_id": run_id,
                "source_records": source.source_records if source.source_records is not None else len(source.frame),
            },
        )


def load_raw(connection: Connection, run_id: UUID, source: ExtractedSource) -> int:
    missing = set(source.column_mapping) - set(source.frame.columns)
    if missing:
        raise ValueError(f"{source.source_name} is missing expected columns: {sorted(missing)}")

    columns = [
        "ingestion_run_id",
        "source_file_name",
        "source_row_number",
        *source.column_mapping.values(),
        "source_payload",
    ]
    placeholders = [
        ":ingestion_run_id",
        ":source_file_name",
        ":source_row_number",
        *[f":{column}" for column in source.column_mapping.values()],
        "CAST(:source_payload AS JSONB)",
    ]
    statement = text(f"INSERT INTO {source.raw_table} ({', '.join(columns)}) VALUES ({', '.join(placeholders)})")
    records = []
    for source_row_number, row in zip(source.row_numbers, source.frame.to_dict(orient="records")):
        record = {
            target: "" if row.get(input_name) is None else str(row.get(input_name, ""))
            for input_name, target in source.column_mapping.items()
        }
        record.update(
            {
                "ingestion_run_id": str(run_id),
                "source_file_name": source.file_path.name,
                "source_row_number": source_row_number,
                "source_payload": json.dumps(row, default=str, ensure_ascii=False),
            }
        )
        records.append(record)
    if records:
        connection.execute(statement, records)
    connection.execute(
        text("""
        INSERT INTO audit.source_ingestions
            (run_id, source_name, source_file_name, source_file_path, file_checksum_sha256, source_format, extracted_records)
        VALUES (:run_id, :source_name, :file_name, :file_path, :checksum, :source_format, :records)
    """),
        {
            "run_id": str(run_id),
            "source_name": source.source_name,
            "file_name": source.file_path.name,
            "file_path": str(source.file_path.resolve()),
            "checksum": source.checksum_sha256,
            "source_format": source.source_format,
            "records": len(records),
        },
    )
    return len(records)
