"""Shared extraction contracts and file metadata capture."""

from __future__ import annotations

from dataclasses import dataclass
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

    @property
    def checksum_sha256(self) -> str:
        return sha256(self.file_path.read_bytes()).hexdigest()


def extract_delimited(
    source_name: str, raw_table: str, file_path: Path, column_mapping: dict[str, str]
) -> ExtractedSource:
    return ExtractedSource(
        source_name,
        raw_table,
        file_path,
        "CSV",
        pd.read_csv(file_path, dtype=str, keep_default_na=False),
        column_mapping,
    )


def extract_json(source_name: str, raw_table: str, file_path: Path, column_mapping: dict[str, str]) -> ExtractedSource:
    return ExtractedSource(
        source_name, raw_table, file_path, "JSON", pd.read_json(file_path, dtype=False), column_mapping
    )
