"""Consistent console logging for pipeline modules."""

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from pipeline.config import settings

APP_TIMEZONE = ZoneInfo(settings.app_timezone)

LOG_FIELDS = (
    "run_id",
    "pipeline_name",
    "status",
    "start_time",
    "end_time",
    "extracted_records",
    "source_records",
    "skipped_unchanged_records",
    "source_metrics",
    "report_summary",
    "outcome_message",
    "valid_records",
    "duplicate_records",
    "invalid_records",
    "loaded_records",
    "validated_records",
    "rejected_records",
    "incremental_records",
    "staged_records",
    "dimension_records",
    "fact_inserted_records",
    "fact_skipped_records",
    "duration_seconds",
    "error_message",
    "smtp_host",
    "smtp_port",
    "attempt",
    "max_attempts",
    "request_method",
    "request_path",
    "status_code",
    "duration_ms",
)


class _LoggerNameFilter(logging.Filter):
    def __init__(self, prefix: str):
        super().__init__()
        self.prefix = prefix

    def filter(self, record: logging.LogRecord) -> bool:
        return record.name == self.prefix or record.name.startswith(f"{self.prefix}.")


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(APP_TIMEZONE).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in LOG_FIELDS:
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class _ApplicationTimeFormatter(logging.Formatter):
    """Render non-JSON logs in the configured application timezone."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timestamp = datetime.fromtimestamp(record.created, APP_TIMEZONE)
        return timestamp.strftime(datefmt) if datefmt else timestamp.isoformat()


class _PrettyConsoleFormatter(_ApplicationTimeFormatter):
    """Render pipeline completion logs as a complete, readable console report."""

    @staticmethod
    def _mapping(value) -> dict:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _items(value) -> list:
        return value if isinstance(value, list) else []

    @staticmethod
    def _field_counts(finding: dict) -> str:
        fields = finding.get("by_field") or {}
        return ", ".join(f"{field}: {count}" for field, count in fields.items())

    def _format_pipeline_completion(self, record: logging.LogRecord) -> str:
        summary = self._mapping(getattr(record, "report_summary", {}))
        raw = self._mapping(summary.get("raw"))
        product_master = self._mapping(raw.get("product_master"))
        quality_staging = summary.get("quality_staging")
        warehouse = self._mapping(summary.get("warehouse"))
        status = getattr(record, "status", "UNKNOWN")
        lines = [
            f"{'=' * 72}",
            f"PIPELINE {status}",
            f"{'=' * 72}",
            f"Run ID          : {getattr(record, 'run_id', '—')}",
            f"Pipeline        : {getattr(record, 'pipeline_name', '—')}",
            f"Mulai           : {getattr(record, 'start_time', '—')}",
            f"Selesai         : {getattr(record, 'end_time', '—')}",
            f"Durasi          : {getattr(record, 'duration_seconds', '—')} detik",
            "",
            "RINGKASAN RECORD",
            f"- Source data transaksi  : {getattr(record, 'source_records', 0)}",
            f"- Baru atau berubah      : {getattr(record, 'extracted_records', 0)}",
            f"- Valid                  : {getattr(record, 'validated_records', 0)}",
            f"- Ditolak                : {getattr(record, 'rejected_records', 0)}",
            f"- Duplikat               : {getattr(record, 'duplicate_records', 0)}",
            f"- Fact ditulis           : {getattr(record, 'loaded_records', 0)}",
            "",
            "RINCIAN PER SUMBER",
        ]
        processed_sources = [
            source
            for source in self._items(getattr(record, "source_metrics", []))
            if isinstance(source, dict) and source.get("extracted_records", 0)
        ]
        for source in processed_sources:
            if not isinstance(source, dict):
                continue
            lines.append(
                "- {name}: kandidat {extracted}"
                " | valid {valid} | ditolak {rejected} | duplikat {duplicate}".format(
                    name=source.get("source_name", "—"),
                    extracted=source.get("extracted_records", 0),
                    valid=source.get("validated_records", 0),
                    rejected=source.get("rejected_records", 0),
                    duplicate=source.get("duplicate_records", 0),
                )
            )
        if not processed_sources:
            lines.append("- Tidak ada sumber baru atau berubah untuk diproses.")
        lines.extend(
            [
                "",
                "RAW LAYER",
                f"- Transaksi baru/berubah : {raw.get('new_or_changed', 0)} | dimuat ke Raw: {raw.get('inserted_to_raw', 0)} | total Raw: {raw.get('total_transactions_in_raw', 0)}",
            ]
        )
        if product_master.get("new_or_changed", 0) or product_master.get("inserted_to_raw", 0):
            lines.append(
                f"- Master Produk baru/berubah: {product_master.get('new_or_changed', 0)} | dimuat ke Raw: {product_master.get('inserted_to_raw', 0)} | total Raw: {product_master.get('total_in_raw', 0)}"
            )
        if isinstance(quality_staging, dict):
            lines.extend(["", "QUALITY CHECK & STAGING"])
            for key, label in (
                ("missing_value", "Nilai kosong"),
                ("duplicate_business_key", "Duplikat business key"),
                ("invalid_quantity", "Kuantitas tidak valid"),
                ("invalid_price", "Harga atau amount tidak valid"),
                ("invalid_status", "Status tidak valid"),
                ("invalid_date", "Tanggal tidak valid"),
                ("unmapped_product", "Produk tidak termapping"),
                ("type_cast_failure", "Gagal konversi tipe"),
            ):
                finding = self._mapping(quality_staging.get(key))
                count = finding.get("total", 0)
                if count:
                    details = self._field_counts(finding)
                    lines.append(f"- {label}: {count}" + (f" ({details})" if details else ""))
            lines.extend(
                [
                    f"- Lolos ke Staging: {quality_staging.get('passed_to_staging', 0)}",
                    f"- Dimuat ke Staging: {quality_staging.get('written_to_staging', 0)}",
                ]
            )
            for source in self._items(quality_staging.get("by_source")):
                if not isinstance(source, dict):
                    continue
                lines.append(
                    "  {name}: diproses {processed} | valid {valid} | ditolak {rejected} | duplikat {duplicate}".format(
                        name=source.get("source_name", "—"),
                        processed=source.get("processed", 0),
                        valid=source.get("valid", 0),
                        rejected=source.get("rejected", 0),
                        duplicate=source.get("duplicate", 0),
                    )
                )
        else:
            lines.extend(["", "QUALITY CHECK & STAGING", "- Tidak dijalankan karena tidak ada data baru atau berubah."])
        lines.extend(
            [
                "",
                "WAREHOUSE",
                f"- Fact siap dimuat      : {warehouse.get('eligible_facts', 0)}",
                f"- Fact baru             : {warehouse.get('inserted_facts', 0)}",
                f"- Fact diperbarui       : {warehouse.get('updated_facts', 0)}",
                f"- Total fact ditulis    : {warehouse.get('facts_written', 0)}",
                "",
                f"CATATAN: {getattr(record, 'outcome_message', '—')}",
            ]
        )
        if getattr(record, "error_message", None):
            lines.append(f"ERROR: {record.error_message}")
        return "\n".join(lines)

    def format(self, record: logging.LogRecord) -> str:
        if record.getMessage() == "pipeline_run_completed":
            return self._format_pipeline_completion(record)
        timestamp = self.formatTime(record)
        details = []
        for key in LOG_FIELDS:
            if not hasattr(record, key):
                continue
            value = getattr(record, key)
            if isinstance(value, (dict, list)):
                value = json.dumps(value, ensure_ascii=False, default=str)
            details.append(f"{key}={value}")
        suffix = f" | {' | '.join(details)}" if details else ""
        return f"{timestamp} | {record.levelname} | {record.name} | {record.getMessage()}{suffix}"


def _configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_arunika_configured", False):
        return
    root.setLevel(settings.log_level.upper())
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    console_format = os.getenv("LOG_FORMAT", "text").lower()
    formatter = {
        "json": _JsonFormatter(),
        "pretty": _PrettyConsoleFormatter(),
    }.get(console_format, _ApplicationTimeFormatter("%(asctime)s | %(levelname)s | %(name)s | %(message)s"))

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    for prefix, filename in (("pipeline", "pipeline.log"), ("dashboard", "dashboard.log")):
        file_handler = logging.FileHandler(log_dir / filename, encoding="utf-8")
        # Keep file logs readable like the CLI report. Pipeline completion
        # events become a sectioned summary; other events remain text lines
        # with their available operational fields.
        file_handler.setFormatter(_PrettyConsoleFormatter())
        file_handler.addFilter(_LoggerNameFilter(prefix))
        root.addHandler(file_handler)
    root._arunika_configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_logging()
    logger = logging.getLogger(name)
    return logger
