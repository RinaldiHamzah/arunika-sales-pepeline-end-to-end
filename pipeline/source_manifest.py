"""Metadata deklarasi snapshot untuk rekonsiliasi sumber yang aman."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from pipeline.validation.contracts import SOURCE_NAMES

MANIFEST_NAME = "source_manifest.json"
INGESTION_MODES = {"FULL_SNAPSHOT", "INCREMENTAL_BATCH"}


@dataclass(frozen=True)
class SourceDeclaration:
    """Deklarasi cakupan satu sumber untuk satu ingestion."""

    ingestion_mode: str = "INCREMENTAL_BATCH"
    snapshot_scope: str | None = None
    snapshot_timestamp: datetime | None = None
    snapshot_completeness: str = "UNKNOWN"

    @property
    def is_reconcilable(self) -> bool:
        return (
            self.ingestion_mode == "FULL_SNAPSHOT"
            and self.snapshot_scope == "ALL_HISTORY"
            and self.snapshot_timestamp is not None
            and self.snapshot_completeness == "COMPLETE"
        )


def load_source_manifest(source_dir: Path) -> dict[str, SourceDeclaration]:
    """Baca deklarasi; tanpa manifest semua file dianggap batch yang tidak lengkap."""
    path = Path(source_dir) / MANIFEST_NAME
    if not path.exists():
        return {name: SourceDeclaration() for name in SOURCE_NAMES.values()}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"{MANIFEST_NAME} tidak dapat dibaca sebagai JSON valid") from error
    if not isinstance(payload, dict) or set(payload) != {"sources"} or not isinstance(payload["sources"], dict):
        raise ValueError(f"{MANIFEST_NAME} harus memiliki objek tingkat atas 'sources'")

    declarations = {name: SourceDeclaration() for name in SOURCE_NAMES.values()}
    for source_name, item in payload["sources"].items():
        if source_name not in declarations or not isinstance(item, dict):
            raise ValueError(f"Deklarasi sumber tidak dikenal atau tidak valid: {source_name}")
        mode = str(item.get("ingestion_mode", "")).upper()
        completeness = str(item.get("snapshot_completeness", "UNKNOWN")).upper()
        scope = item.get("snapshot_scope")
        timestamp_text = item.get("snapshot_timestamp")
        if mode not in INGESTION_MODES:
            raise ValueError(f"ingestion_mode untuk {source_name} harus FULL_SNAPSHOT atau INCREMENTAL_BATCH")
        if completeness not in {"COMPLETE", "PARTIAL", "UNKNOWN"}:
            raise ValueError(f"snapshot_completeness untuk {source_name} tidak valid")
        timestamp = None
        if timestamp_text:
            try:
                timestamp = datetime.fromisoformat(str(timestamp_text).replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError(f"snapshot_timestamp untuk {source_name} harus ISO-8601") from error
            if timestamp.tzinfo is None:
                raise ValueError(f"snapshot_timestamp untuk {source_name} harus memiliki zona waktu")
        declaration = SourceDeclaration(mode, str(scope) if scope else None, timestamp, completeness)
        if mode == "FULL_SNAPSHOT" and not declaration.is_reconcilable:
            raise ValueError(f"FULL_SNAPSHOT untuk {source_name} harus menyatakan ALL_HISTORY, timestamp, dan COMPLETE")
        declarations[source_name] = declaration
    return declarations
