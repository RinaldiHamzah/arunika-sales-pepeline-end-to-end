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


def _mark_stale_return_correction(connection, run_id, row_number, raw, reason) -> None:
    """Flag an invalid correction when its return event already exists in the fact table.

    The shared stale-correction audit table stores ``CHANNEL:return_id`` in
    ``source_order_id`` for RETURN_EVENTS; ``source_line_number`` stores the
    return line number. This preserves the return business key, including its
    channel, and separates it from sales order-line keys.
    """
    source_name = str(raw.get("source_name") or "").strip().upper()
    source_name = {"OFFLINE": "OFFLINE_STORE"}.get(source_name, source_name)
    return_id = str(raw.get("return_id") or "").strip()
    raw_line = str(raw.get("return_line_number") or "").strip()
    if source_name not in {"SHOPEE", "TOKOPEDIA", "WEBSITE", "OFFLINE_STORE"}:
        source_name = None
    if not return_id:
        return
    line_number = int(raw_line) if raw_line.isdecimal() else None
    if line_number is not None and (line_number <= 0 or line_number > 2147483647):
        line_number = None

    connection.execute(
        text("""
            INSERT INTO audit.stale_fact_corrections
                (source_name, source_order_id, source_line_number, rejected_run_id,
                 source_row_number, rejection_reason, resolved_at, resolved_run_id)
            SELECT 'RETURN_EVENTS', fact.source_name || ':' || fact.return_id, fact.return_line_number,
                   CAST(:run_id AS UUID), :source_row_number, :rejection_reason,
                   NULL::TIMESTAMPTZ, NULL::UUID
            FROM warehouse.fact_returns AS fact
            WHERE (CAST(:source_name AS VARCHAR) IS NULL OR fact.source_name = :source_name)
              AND fact.return_id = :return_id
              AND (CAST(:line_number AS INTEGER) IS NULL OR fact.return_line_number = :line_number)
            ON CONFLICT (source_name, source_order_id, source_line_number) DO UPDATE SET
                rejected_run_id = EXCLUDED.rejected_run_id,
                source_row_number = EXCLUDED.source_row_number,
                rejection_reason = EXCLUDED.rejection_reason,
                rejected_at = CURRENT_TIMESTAMP,
                resolved_at = NULL,
                resolved_run_id = NULL,
                updated_at = CURRENT_TIMESTAMP
        """),
        {
            "run_id": str(run_id),
            "source_row_number": row_number,
            "rejection_reason": reason,
            "source_name": source_name,
            "return_id": return_id,
            "line_number": line_number,
        },
    )


def load_return_staging(connection: Connection, run_id: UUID, source: ExtractedSource) -> dict[str, int]:
    """Validasi dan simpan event return kanonis ke staging sebelum warehouse."""
    if source.frame.empty:
        return {"staged": 0, "rejected": 0, "valid": 0, "duplicates": 0, "rejection_reasons": {}}

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
        _mark_stale_return_correction(connection, run_id, row_number, raw, reason)
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
        # A valid re-submission resolves a previous warning even when its
        # canonical hash matches the last valid staging/fact row and therefore
        # produces no staging upsert rowcount.
        connection.execute(
            text("""
                UPDATE audit.stale_fact_corrections AS stale
                SET resolved_at = CURRENT_TIMESTAMP,
                    resolved_run_id = :run_id,
                    updated_at = CURRENT_TIMESTAMP
                FROM unnest(
                    CAST(:source_names AS VARCHAR[]),
                    CAST(:return_ids AS TEXT[]),
                    CAST(:line_numbers AS INTEGER[])
                ) AS valid(source_name, return_id, return_line_number)
                WHERE stale.source_name = 'RETURN_EVENTS'
                  AND stale.source_order_id = valid.source_name || ':' || valid.return_id
                  AND stale.source_line_number = valid.return_line_number
                  AND stale.resolved_at IS NULL
            """),
            {
                "run_id": str(run_id),
                "source_names": [row["source_name"] for row in accepted],
                "return_ids": [row["return_id"] for row in accepted],
                "line_numbers": [row["return_line_number"] for row in accepted],
            },
        )
    return {
        "staged": staged_count,
        "rejected": len(rejected),
        "valid": len(accepted),
        "duplicates": duplicates,
        "rejection_reasons": dict(counts) if rejected else {},
    }


def load_return_facts(connection: Connection, run_id: UUID) -> dict[str, int]:
    """Muat baris kanonis dari staging ke fact dan pisahkan insert/update."""
    candidates = connection.execute(text("""
        SELECT source_name, return_id, return_line_number
        FROM staging.stg_returns
        WHERE ingestion_run_id = :run_id AND is_valid
    """), {"run_id": str(run_id)}).mappings().all()
    if not candidates:
        return {"inserted": 0, "updated": 0, "total": 0}
    names = [row["source_name"] for row in candidates]
    ids = [row["return_id"] for row in candidates]
    lines = [row["return_line_number"] for row in candidates]
    existing = connection.execute(text("""
        SELECT fact.source_name, fact.return_id, fact.return_line_number
        FROM warehouse.fact_returns AS fact
        JOIN unnest(CAST(:source_names AS VARCHAR[]), CAST(:return_ids AS TEXT[]),
                    CAST(:line_numbers AS INTEGER[]))
             AS candidate(source_name, return_id, return_line_number)
          ON candidate.source_name = fact.source_name
         AND candidate.return_id = fact.return_id
         AND candidate.return_line_number = fact.return_line_number
    """), {"source_names": names, "return_ids": ids, "line_numbers": lines}).mappings().all()
    existing_keys = {
        (row["source_name"], row["return_id"], row["return_line_number"])
        for row in existing
    }
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
    total = max(result.rowcount, 0)
    inserted = sum(
        (row["source_name"], row["return_id"], row["return_line_number"]) not in existing_keys
        for row in candidates
    )
    inserted = min(inserted, total)
    return {"inserted": inserted, "updated": max(0, total - inserted), "total": total}


def _record_hash(row: dict) -> str:
    import hashlib

    payload = {key: str(value) if value is not None else None for key, value in row.items()}
    payload.pop("source_row_number", None)
    payload.pop("source_raw_record_id", None)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
