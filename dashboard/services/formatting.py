"""Pemformatan data API JSON."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Iterable, Mapping


def serializable(rows: Iterable[Mapping]) -> list[dict]:
    """Ubah baris basis data menjadi kamus yang aman untuk JSON."""
    result = []
    for row in rows:
        item = dict(row)
        for key, value in item.items():
            if isinstance(value, (date, Decimal)):
                item[key] = value.isoformat() if isinstance(value, date) else float(value)
        result.append(item)
    return result


def operation_runs_for_display(rows: Iterable[Mapping]) -> list[dict]:
    """Sajikan bukti run ke UI tanpa metrik audit yang hanya tersedia pada snapshot."""
    visible = []
    for row in serializable(rows):
        row.pop("source_records", None)
        row.pop("skipped_unchanged_records", None)
        row.pop("fact_skipped_records", None)
        row["source_metrics"] = [
            {
                key: source.get(key)
                for key in (
                    "source_name",
                    "extracted_records",
                    "validated_records",
                    "rejected_records",
                    "duplicate_records",
                )
            }
            for source in (row.get("source_metrics") or [])
        ]
        visible.append(row)
    return visible
