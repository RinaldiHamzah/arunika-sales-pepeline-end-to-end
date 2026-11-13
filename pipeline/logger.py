"""Pencatatan log pipeline."""

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
    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        timestamp = datetime.fromtimestamp(record.created, APP_TIMEZONE)
        return timestamp.strftime(datefmt) if datefmt else timestamp.isoformat()


class _PrettyConsoleFormatter(_ApplicationTimeFormatter):
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
        auxiliary_sources = {
            source.get("source_name"): source
            for source in self._items(summary.get("auxiliary_sources"))
            if isinstance(source, dict)
        }
        database_counts = self._mapping(summary.get("database_table_counts"))
        quality_staging = summary.get("quality_staging")
        warehouse = self._mapping(summary.get("warehouse"))
        return_warehouse = self._mapping(summary.get("return_warehouse"))
        dimensions = self._mapping(summary.get("dimensions"))
        source_metrics = {
            source.get("source_name"): source
            for source in self._items(getattr(record, "source_metrics", []))
            if isinstance(source, dict)
        }
        quality_sources = {
            source.get("source_name"): source
            for source in self._items(self._mapping(quality_staging).get("by_source"))
            if isinstance(source, dict)
        }
        channel_names = ("SHOPEE", "TOKOPEDIA", "WEBSITE", "OFFLINE_STORE")
        sales_candidates = sum(int(source_metrics.get(name, {}).get("extracted_records", 0) or 0)
                               for name in channel_names)
        promo = auxiliary_sources.get("PROMO_MASTER", {})
        returns = auxiliary_sources.get("RETURN_EVENTS", {})
        product_candidate = int(source_metrics.get("PRODUCT_MASTER", {}).get("extracted_records", 0) or 0)
        promo_candidate = int(promo.get("processed", 0) or 0)
        return_candidate = int(returns.get("processed", 0) or 0)
        all_source_candidates = sales_candidates + product_candidate + promo_candidate + return_candidate
        sales_valid = sum(int(source_metrics.get(name, {}).get("validated_records", 0) or 0)
                          for name in channel_names)
        product_valid = int(source_metrics.get("PRODUCT_MASTER", {}).get("validated_records", 0) or 0)
        all_valid = sales_valid + product_valid + int(promo.get("validated", 0) or 0) + int(returns.get("validated", 0) or 0)
        all_rejected = (sum(int(source_metrics.get(name, {}).get("rejected_records", 0) or 0)
                            for name in (*channel_names, "PRODUCT_MASTER"))
                        + int(promo.get("rejected", 0) or 0) + int(returns.get("rejected", 0) or 0))
        all_duplicates = (sum(int(source_metrics.get(name, {}).get("duplicate_records", 0) or 0)
                              for name in (*channel_names, "PRODUCT_MASTER"))
                          + int(promo.get("duplicates", 0) or 0) + int(returns.get("duplicates", 0) or 0))
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
            f"- Kandidat Transaksi kanal : {sales_candidates}",
            f"- Kandidat Master Produk   : {product_candidate}",
            f"- Kandidat Promo baru      : {promo_candidate}",
            f"- Kandidat Return baru     : {return_candidate}",
            f"- Total baris semua sumber : {all_source_candidates}",
            f"- Total valid              : {all_valid}",
            f"- Total ditolak            : {all_rejected}",
            f"- Total duplikat           : {all_duplicates}",
            f"- Fact Sales ditulis       : {getattr(record, 'loaded_records', 0)}",
            f"- Fact Return ditulis      : {return_warehouse.get('facts_written', returns.get('warehouse_written', 0))}",
            "",
            "RINCIAN PER SUMBER",
        ]
        for name in ("PRODUCT_MASTER", "PROMO_MASTER", *channel_names, "RETURN_EVENTS"):
            source = source_metrics.get(name)
            if name == "PROMO_MASTER":
                source = promo
                if source:
                    lines.append(
                        "- Master Promo: katalog {source_records} | valid katalog {catalog_valid} | baru/berubah {processed} | "
                        "ditolak {rejected} | duplikat {duplicates} | Raw +{raw} | Dimensi Promo diproses {dimension}".format(
                            source_records=source.get("source_records", 0), processed=source.get("processed", 0),
                            catalog_valid=source.get("catalog_validated", source.get("validated", 0)),
                            valid=source.get("validated", 0), rejected=source.get("rejected", 0),
                            duplicates=source.get("duplicates", 0), raw=source.get("raw_inserted", 0),
                            dimension=source.get("warehouse_written", 0) or 0,
                        )
                    )
                else:
                    lines.append("Master Promo: belum ada metrik.")
                continue
            if name == "RETURN_EVENTS":
                source = returns
                if source:
                    lines.append(
                        "- Return: sumber {source_records} | berubah {processed} | valid {valid} | "
                        "ditolak {rejected} | duplikat {duplicates} | Raw +{raw} | Staging +{staging} | Fact +{fact}".format(
                            source_records=source.get("source_records", 0), processed=source.get("processed", 0),
                            valid=source.get("validated", 0), rejected=source.get("rejected", 0),
                            duplicates=source.get("duplicates", 0), raw=source.get("raw_inserted", 0),
                            staging=source.get("staging_written", 0), fact=source.get("warehouse_written", 0),
                        )
                    )
                else:
                    lines.append("- Return: belum ada metrik.")
                continue
            if not source:
                lines.append(f"- {name}: belum ada metrik.")
                continue
            if name == "PRODUCT_MASTER":
                source_label = "Master Produk"
            else:
                source_label = name
            lines.append(
                "- {name}: sumber {source_total} | kandidat {candidate} | valid {valid} | "
                "ditolak {rejected} | duplikat dilewati {duplicates}{extra}".format(
                    name=source_label, source_total=source.get("source_records", 0),
                    candidate=source.get("extracted_records", 0),
                    valid=source.get("validated_records", 0), rejected=source.get("rejected_records", 0),
                    duplicates=source.get("duplicate_records", 0),
                    extra=(
                        f" | Raw +{product_master.get('inserted_to_raw', 0)} | "
                        f"Dimensi Produk diproses {dimensions.get('products_processed', 0)}"
                        if name == "PRODUCT_MASTER" else ""
                    ),
                )
            )
        lines.extend(
            [
                "",
                "RAW LAYER",
                f"- Transaksi kanal baru/berubah: {raw.get('new_or_changed', 0)} | Raw ditambah {raw.get('inserted_to_raw', 0)} | total Raw: {raw.get('total_transactions_in_raw', 0)}",
            ]
        )
        if product_master.get("new_or_changed", 0) or product_master.get("inserted_to_raw", 0):
            lines.append(
                f"- Master Produk baru/berubah: {product_master.get('new_or_changed', 0)} | Raw ditambah {product_master.get('inserted_to_raw', 0)} | total Raw: {product_master.get('total_in_raw', 0)}"
            )
        if promo:
            lines.append(
                f"- Master Promo baru/berubah: {promo.get('processed', 0)} | Raw ditambah {promo.get('raw_inserted', 0)} | total Raw: {database_counts.get('raw.promo_master', '—')}"
            )
        if returns:
            lines.append(
                f"- Return baru/berubah: {returns.get('processed', 0)} | Raw ditambah {returns.get('raw_inserted', 0)} | total Raw: {database_counts.get('raw.return_events', '—')}"
            )
        if isinstance(quality_staging, dict):
            lines.extend(["", "QUALITY CHECK — SALES"])
            for key, label in (
                ("missing_value", "Nilai kosong"),
                ("duplicate_business_key", "Baris terdampak duplikat business key"),
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
        else:
            lines.extend(["", "QUALITY CHECK — SALES", "- Tidak dijalankan karena tidak ada data baru atau berubah."])
        return_reasons = self._mapping(returns.get("rejection_reasons"))
        lines.extend(
            [
                "",
                "QUALITY CHECK — RETURN",
                f"- Baris sumber: {returns.get('source_records', 0)} | berubah: {returns.get('processed', 0)} | tidak berubah: {returns.get('unchanged', 0)}",
                f"- Diperiksa: {returns.get('processed', 0)}",
                f"- Valid: {returns.get('validated', 0)}",
                f"- Ditolak: {returns.get('rejected', 0)}",
                f"- Duplikat: {returns.get('duplicates', 0)}",
            ]
        )
        if return_reasons:
            lines.append("")
            categories = {
                "Nilai wajib kosong/tidak valid": 0,
                "Business key duplikat": 0,
                "Tanggal tidak valid": 0,
                "Status retur/refund tidak valid": 0,
                "Jumlah retur tidak valid/melebihi penjualan": 0,
                "Nilai refund tidak valid/melebihi penjualan": 0,
                "Referensi transaksi tidak valid": 0,
            }
            for reason, count in sorted(return_reasons.items()):
                normalized = str(reason).lower()
                if "duplikat" in normalized or "business key" in normalized:
                    category = "Business key duplikat"
                elif "date" in normalized or "tanggal" in normalized or "format yyyy-mm-dd" in normalized:
                    category = "Tanggal tidak valid"
                elif "status" in normalized:
                    category = "Status retur/refund tidak valid"
                elif "quantity" in normalized or "jumlah retur" in normalized:
                    category = "Jumlah retur tidak valid/melebihi penjualan"
                elif "refund" in normalized or "net amount" in normalized:
                    category = "Nilai refund tidak valid/melebihi penjualan"
                elif "tidak ditemukan" in normalized or "cancelled" in normalized or "merujuk" in normalized:
                    category = "Referensi transaksi tidak valid"
                else:
                    category = "Nilai wajib kosong/tidak valid"
                categories[category] += int(count or 0)
            for label, count in categories.items():
                if count:
                    lines.append(f"- {label}: {count}")
            lines.append("Rincian: " + " | ".join(
                f"{reason}: {count}" for reason, count in sorted(return_reasons.items())
            ))
        elif returns.get("rejected", 0):
            lines.append("")
        lines.extend(["", "RINCIAN VALIDASI PER SUMBER"])
        for name in ("PRODUCT_MASTER", "PROMO_MASTER", "SHOPEE", "TOKOPEDIA", "WEBSITE", "OFFLINE_STORE", "RETURN_EVENTS"):
            if name == "PROMO_MASTER":
                source = promo
                if source:
                    lines.append(
                        "  PROMO_MASTER: katalog dicek {checked} | baru/berubah {processed} | valid {valid} | "
                        "ditolak {rejected} | duplikat dilewati {duplicates}".format(
                            checked=source.get("catalog_checked", source.get("source_records", 0)),
                            processed=source.get("processed", 0), valid=source.get("catalog_validated", source.get("validated", 0)),
                            rejected=source.get("rejected", 0),
                            duplicates=source.get("catalog_duplicates", source.get("duplicates", 0)),
                        )
                    )
                    if source.get("promo_codes_checked") is not None:
                        lines.append(
                            "    Kode promo pada kanal: diperiksa {checked} | cocok dengan master {matched}".format(
                                checked=source.get("promo_codes_checked", 0),
                                matched=source.get("promo_codes_matched", 0),
                            )
                        )
                else:
                    lines.append("  PROMO_MASTER: belum ada metrik.")
                continue
            if name == "RETURN_EVENTS":
                source = returns
                if source:
                    lines.append(
                        "  RETURN_EVENTS: diproses {processed} | tidak berubah {unchanged} | valid {valid} | "
                        "ditolak {rejected} | duplikat dilewati {duplicates}".format(
                            processed=source.get("processed", 0), unchanged=source.get("unchanged", 0),
                            valid=source.get("validated", 0), rejected=source.get("rejected", 0),
                            duplicates=source.get("duplicates", 0),
                        )
                    )
                else:
                    lines.append("  RETURN_EVENTS: belum ada metrik.")
                continue
            source = quality_sources.get(name) or source_metrics.get(name)
            if source:
                lines.append(
                    "  {name}: diproses {processed} | valid {valid} | ditolak {rejected} | duplikat dilewati {duplicate}".format(
                        name=name, processed=source.get("processed", source.get("extracted_records", 0)),
                        valid=source.get("valid", source.get("validated_records", 0)),
                        rejected=source.get("rejected", source.get("rejected_records", 0)),
                        duplicate=source.get("duplicate", source.get("duplicate_records", 0)),
                    )
                )
            else:
                lines.append(f"  {name}: belum ada metrik.")
        lines.extend(
            [
                "",
                "STAGING LAYER",
                f"- Sales lolos ke Staging: {quality_staging.get('passed_to_staging', 0) if isinstance(quality_staging, dict) else 0}",
                f"- Sales dimuat ke Staging: {quality_staging.get('written_to_staging', 0) if isinstance(quality_staging, dict) else 0}",
                f"- Return lolos ke Staging: {returns.get('validated', 0)}",
                f"- Return dimuat ke Staging: {returns.get('staging_written', 0)}",
            ]
        )
        lines.extend(
            [
                "",
                "WAREHOUSE LAYER",
                f"- Fact Sales siap dimuat : {warehouse.get('eligible_facts', 0)}",
                f"- Fact Sales baru        : {warehouse.get('inserted_facts', 0)}",
                f"- Fact Sales diperbarui  : {warehouse.get('updated_facts', 0)}",
                f"- Total Fact Sales ditulis: {warehouse.get('facts_written', 0)}",
                f"- Fact Return siap dimuat: {return_warehouse.get('eligible_facts', returns.get('validated', 0))}",
                f"- Fact Return baru       : {return_warehouse.get('inserted_facts', 0)}",
                f"- Fact Return diperbarui : {return_warehouse.get('updated_facts', 0)}",
                f"- Total Fact Return ditulis: {return_warehouse.get('facts_written', returns.get('warehouse_written', 0))}",
            ]
        )
        if database_counts:
            lines.extend(["", "JUMLAH BARIS DALAM DATABASE"])
            for table in (
                "raw.shopee_orders",
                "raw.tokopedia_transactions",
                "raw.website_transactions",
                "raw.offline_store_sales",
                "raw.product_master",
                "raw.promo_master",
                "raw.return_events",
                "staging.stg_sales",
                "staging.stg_returns",
                "warehouse.fact_sales",
                "warehouse.fact_returns",
            ):
                lines.append(f"- {table:<34}: {database_counts.get(table, 'Belum direkam')}")
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

    log_files = {
        "pipeline": Path(os.getenv("PIPELINE_LOG_FILE", str(log_dir / "pipeline.log"))),
        "dashboard": log_dir / "dashboard.log",
    }
    for prefix, path in log_files.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(path, encoding="utf-8")
        file_handler.setFormatter(_PrettyConsoleFormatter())
        file_handler.addFilter(_LoggerNameFilter(prefix))
        root.addHandler(file_handler)
    root._arunika_configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_logging()
    logger = logging.getLogger(name)
    return logger
