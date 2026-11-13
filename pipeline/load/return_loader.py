"""Pemuatan Raw dan Warehouse untuk kejadian retur/refund."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.engine import Connection

from pipeline.extract.base import ExtractedSource
from pipeline.returns import normalize_return_record


def load_return_raw(connection: Connection, run_id: UUID, source: ExtractedSource) -> int:
    """Simpan payload retur tanpa transformasi dan catat ingestion file."""
    columns = list(source.column_mapping.values())
    names = ["ingestion_run_id", "source_file_name", "source_row_number", *columns, "source_payload"]
    values = [":ingestion_run_id", ":source_file_name", ":source_row_number"]
    values.extend(f":{column}" for column in columns)
    values.append("CAST(:source_payload AS JSONB)")
    statement = text(f"INSERT INTO raw.return_events ({', '.join(names)}) VALUES ({', '.join(values)})")
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
            VALUES (:run_id, 'RETURN_EVENTS', :file_name, :file_path,
                    :checksum, 'CSV', :records)
        """),
        {
            "run_id": str(run_id),
            "file_name": source.file_path.name,
            "file_path": str(source.file_path.resolve()),
            "checksum": source.checksum_sha256,
            "records": len(records),
        },
    )
    return len(records)


def _reject(connection, run_id, row_number, raw, reason) -> None:
    connection.execute(
        text("""
            INSERT INTO audit.rejected_records
                (run_id, source_name, source_order_id, source_line_number,
                 source_row_number, rejection_reason, source_payload)
            VALUES (:run_id, 'RETURN_EVENTS', :order_id, :line_number,
                    :row_number, :reason, CAST(:payload AS JSONB))
        """),
        {
            "run_id": str(run_id),
            "order_id": str(raw.get("order_id") or "") or None,
            "line_number": int(raw["order_line_number"])
            if str(raw.get("order_line_number", "")).isdecimal() and int(raw["order_line_number"]) <= 2147483647
            else None,
            "row_number": row_number,
            "reason": reason,
            "payload": json.dumps(raw, default=str, ensure_ascii=False),
        },
    )


def load_return_staging(connection: Connection, run_id: UUID, source: ExtractedSource) -> dict[str, int]:
    """Validasi dan simpan event return kanonis ke staging sebelum warehouse."""
    if source.frame.empty:
        return {"loaded": 0, "rejected": 0}

    raw_ids = {
        row["source_row_number"]: row["raw_record_id"]
        for row in connection.execute(
            text("""
                SELECT raw_record_id, source_row_number
                FROM raw.return_events
                WHERE ingestion_run_id = :run_id AND source_file_name = :file_name
            """),
            {"run_id": str(run_id), "file_name": source.file_path.name},
        ).mappings()
    }
    candidates = []
    rejected = []
    for row_number, raw in zip(source.row_numbers, source.frame.to_dict("records")):
        try:
            normalized = normalize_return_record(raw)
            normalized["source_row_number"] = row_number
            normalized["source_raw_record_id"] = raw_ids.get(row_number)
            if normalized["source_raw_record_id"] is None:
                raise ValueError("Raw return record tidak ditemukan untuk run ini")
            candidates.append((normalized, raw))
        except ValueError as error:
            rejected.append((row_number, raw, str(error)))

    by_event_key = defaultdict(list)
    for candidate, raw in candidates:
        key = (candidate["source_name"], candidate["return_id"], candidate["return_line_number"])
        by_event_key[key].append((candidate, raw))
    duplicate_keys = {
        key for key, rows in by_event_key.items()
        if len({_record_hash(candidate) for candidate, _ in rows}) > 1
    }
    # Duplikat identik diproses sekali; konflik tetap ditolak seluruh versinya.
    duplicates = sum(len(rows) - 1 for key, rows in by_event_key.items() if key not in duplicate_keys)
    candidates = [rows[0] for key, rows in by_event_key.items() if key not in duplicate_keys]
    for key in duplicate_keys:
        for candidate, raw in by_event_key[key]:
            rejected.append((candidate["source_row_number"], raw, "Business key retur duplikat dalam file"))

    accepted = []
    pending_quantity = defaultdict(int)
    pending_refund = defaultdict(Decimal)
    candidates.sort(
        key=lambda item: (
            item[0]["source_name"],
            item[0]["source_order_id"],
            item[0]["source_line_number"],
            item[0]["return_id"],
            item[0]["return_line_number"],
        )
    )
    for candidate, raw in candidates:
        event_key = (candidate["source_name"], candidate["return_id"], candidate["return_line_number"])
        if event_key in duplicate_keys:
            continue
        line_key = (
            candidate["source_name"],
            candidate["source_order_id"],
            candidate["source_line_number"],
        )
        sale = (
            connection.execute(
                text("""
                SELECT quantity, net_amount, sale_status
                FROM warehouse.fact_sales
                WHERE source_name = :source_name
                  AND source_order_id = :order_id
                  AND source_line_number = :line_number
                FOR UPDATE
            """),
                {
                    "source_name": line_key[0],
                    "order_id": line_key[1],
                    "line_number": line_key[2],
                },
            )
            .mappings()
            .first()
        )
        reason = None
        if sale is None:
            reason = "Baris penjualan asal tidak ditemukan di Warehouse"
        elif sale["sale_status"] == "CANCELLED":
            reason = "Retur tidak dapat merujuk ke penjualan CANCELLED"
        else:
            previous = (
                connection.execute(
                    text("""
                    SELECT COALESCE(SUM(quantity_returned), 0) AS quantity_returned,
                           COALESCE(SUM(refund_amount) FILTER (WHERE refund_status = 'PROCESSED'), 0) AS refunded
                    FROM warehouse.fact_returns
                    WHERE source_name = :source_name
                      AND source_order_id = :order_id
                      AND source_line_number = :line_number
                      AND return_status <> 'REJECTED'
                      AND NOT (return_id = :return_id AND return_line_number = :return_line_number)
                """),
                    {
                        "source_name": line_key[0],
                        "order_id": line_key[1],
                        "line_number": line_key[2],
                        "return_id": candidate["return_id"],
                        "return_line_number": candidate["return_line_number"],
                    },
                )
                .mappings()
                .one()
            )
            prior_quantity = int(previous["quantity_returned"]) + pending_quantity[line_key]
            refund_value = candidate["refund_amount"] or Decimal("0.00")
            prior_refund = Decimal(previous["refunded"]) + pending_refund[line_key]
            if (
                candidate["return_status"] != "REJECTED"
                and prior_quantity + candidate["quantity_returned"] > sale["quantity"]
            ):
                reason = "Jumlah retur kumulatif melebihi quantity terjual"
            elif prior_refund + refund_value > sale["net_amount"]:
                reason = "Refund kumulatif melebihi net amount baris penjualan"
            else:
                if candidate["return_status"] != "REJECTED":
                    pending_quantity[line_key] += candidate["quantity_returned"]
                    pending_refund[line_key] += refund_value
        if reason:
            rejected.append((candidate["source_row_number"], raw, reason))
        else:
            accepted.append(candidate)

    for row_number, raw, reason in rejected:
        _reject(connection, run_id, row_number, raw, reason)
    if rejected:
        counts = Counter(reason for _, _, reason in rejected)
        connection.execute(
            text("""
                INSERT INTO audit.data_quality_results
                    (run_id, source_name, rule_name, severity, failed_records, details)
                VALUES (:run_id, 'RETURN_EVENTS', 'INVALID_RETURN_EVENT', 'ERROR',
                        :failed_records, CAST(:details AS JSONB))
            """),
            {
                "run_id": str(run_id),
                "failed_records": len(rejected),
                "details": json.dumps({"category": "return_event", "reasons": dict(counts)}),
            },
        )

    staged_count = 0
    if accepted:
        statement = text("""
                INSERT INTO staging.stg_returns (
                    ingestion_run_id, source_name, source_raw_record_id, source_row_number,
                    return_id, return_line_number, source_order_id, source_line_number,
                    return_date, return_reason, return_status, quantity_returned,
                    refund_amount, refund_status, source_record_hash
                ) VALUES (
                    :ingestion_run_id, :source_name, :source_raw_record_id, :source_row_number,
                    :return_id, :return_line_number, :source_order_id, :source_line_number,
                    :return_date, :return_reason, :return_status, :quantity_returned,
                    :refund_amount, :refund_status, :source_record_hash
                ) ON CONFLICT (source_name, return_id, return_line_number) DO UPDATE SET
                    ingestion_run_id = EXCLUDED.ingestion_run_id,
                    source_raw_record_id = EXCLUDED.source_raw_record_id,
                    source_row_number = EXCLUDED.source_row_number,
                    source_order_id = EXCLUDED.source_order_id,
                    source_line_number = EXCLUDED.source_line_number,
                    return_date = EXCLUDED.return_date,
                    return_reason = EXCLUDED.return_reason,
                    return_status = EXCLUDED.return_status,
                    quantity_returned = EXCLUDED.quantity_returned,
                    refund_amount = EXCLUDED.refund_amount,
                    refund_status = EXCLUDED.refund_status,
                    source_record_hash = EXCLUDED.source_record_hash,
                    transformed_at = CURRENT_TIMESTAMP
                WHERE staging.stg_returns.source_record_hash IS DISTINCT FROM EXCLUDED.source_record_hash
            """)
        for row in accepted:
            result = connection.execute(
                statement,
                {
                    **row,
                    "source_record_hash": _record_hash(row),
                    "ingestion_run_id": str(run_id),
                },
            )
            staged_count += max(result.rowcount, 0)
    return {"staged": staged_count, "rejected": len(rejected), "valid": len(accepted), "duplicates": duplicates}


def load_return_facts(connection: Connection, run_id: UUID) -> int:
    """Muat baris kanonis dari staging ke fact; upsert tetap idempoten."""
    result = connection.execute(text("""
        INSERT INTO warehouse.fact_returns (
            source_name, return_id, return_line_number, source_order_id, source_line_number,
            return_date, return_reason, return_status, quantity_returned, refund_amount,
            refund_status, source_raw_record_id, source_record_hash, ingestion_run_id
        )
        SELECT source_name, return_id, return_line_number, source_order_id, source_line_number,
               return_date, return_reason, return_status, quantity_returned, refund_amount,
               refund_status, source_raw_record_id, source_record_hash, ingestion_run_id
        FROM staging.stg_returns
        WHERE ingestion_run_id = :run_id AND is_valid
        ON CONFLICT (source_name, return_id, return_line_number) DO UPDATE SET
            source_order_id = EXCLUDED.source_order_id,
            source_line_number = EXCLUDED.source_line_number,
            return_date = EXCLUDED.return_date,
            return_reason = EXCLUDED.return_reason,
            return_status = EXCLUDED.return_status,
            quantity_returned = EXCLUDED.quantity_returned,
            refund_amount = EXCLUDED.refund_amount,
            refund_status = EXCLUDED.refund_status,
            source_raw_record_id = EXCLUDED.source_raw_record_id,
            source_record_hash = EXCLUDED.source_record_hash,
            ingestion_run_id = EXCLUDED.ingestion_run_id,
            updated_at = CURRENT_TIMESTAMP
        WHERE warehouse.fact_returns.source_record_hash IS DISTINCT FROM EXCLUDED.source_record_hash
    """), {"run_id": str(run_id)})
    return max(result.rowcount, 0)


def _record_hash(row: dict) -> str:
    import hashlib

    payload = {key: str(value) if value is not None else None for key, value in row.items()}
    payload.pop("source_row_number", None)
    payload.pop("source_raw_record_id", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
