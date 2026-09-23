"""Shared extraction contracts and file metadata capture."""

from __future__ import annotations

from dataclasses import dataclass, replace
from hashlib import sha256
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class ExtractedSource:
    source_name: str
    raw_table: str
    file_path: Path
    source_format: str
    frame: pd.DataFrame
    column_mapping: dict[str, str]
    source_row_numbers: tuple[int, ...] = ()
    captured_checksum: str | None = None
    source_records: int | None = None

    @property
    def checksum_sha256(self) -> str:
        return self.captured_checksum or sha256(self.file_path.read_bytes()).hexdigest()

    @property
    def row_numbers(self) -> tuple[int, ...]:
        """Original CSV row numbers, retained when an incremental subset is used."""
        return self.source_row_numbers or tuple(range(1, len(self.frame) + 1))


def raw_payload_hash(payload: dict) -> str:
    """Hash an exact source row before validation for safe delta detection."""
    import json

    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str, separators=(",", ":"))
    return sha256(canonical.encode("utf-8")).hexdigest()


def filter_unseen_rows(source: ExtractedSource, known_hashes: set[str]) -> ExtractedSource:
    """Return only rows whose raw payload has not already been ingested."""
    if source.frame.empty:
        return source
    selected = [
        (row_number, row)
        for row_number, row in zip(source.row_numbers, source.frame.to_dict(orient="records"))
        if raw_payload_hash(row) not in known_hashes
    ]
    return replace(
        source,
        frame=pd.DataFrame([row for _, row in selected], columns=source.frame.columns),
        source_row_numbers=tuple(row_number for row_number, _ in selected),
    )


def extract_delimited(
    source_name: str, raw_table: str, file_path: Path, column_mapping: dict[str, str], snapshot=None
) -> ExtractedSource:
    from pipeline.validation.data_quality import read_source

    payload = file_path.read_bytes()
    checksum = sha256(payload).hexdigest()
    # Hash bytes to detect changes, but do not parse an unchanged sales file.
    if (
        source_name != "PRODUCT_MASTER"
        and snapshot
        and snapshot["file_checksum_sha256"] == checksum
        and snapshot.get("source_records") is not None
    ):
        frame = pd.DataFrame(columns=list(column_mapping), dtype="string")
        source_records = int(snapshot["source_records"])
    else:
        frame, _ = read_source(file_path, payload=payload)
        source_records = len(frame)
    return ExtractedSource(
        source_name,
        raw_table,
        file_path,
        "CSV",
        frame,
        column_mapping,
        captured_checksum=checksum,
        source_records=source_records,
    )


def extract_json(source_name: str, raw_table: str, file_path: Path, column_mapping: dict[str, str]) -> ExtractedSource:
    return ExtractedSource(
        source_name, raw_table, file_path, "JSON", pd.read_json(file_path, dtype=False), column_mapping
    )
