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


def _configure_logging() -> None:
    root = logging.getLogger()
    if getattr(root, "_arunika_configured", False):
        return
    root.setLevel(settings.log_level.upper())
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    json_format = os.getenv("LOG_FORMAT", "text").lower() == "json"
    formatter = _JsonFormatter() if json_format else _ApplicationTimeFormatter(
        "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
    )

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(console)

    for prefix, filename in (("pipeline", "pipeline.log"), ("dashboard", "dashboard.log")):
        file_handler = logging.FileHandler(log_dir / filename, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.addFilter(_LoggerNameFilter(prefix))
        root.addHandler(file_handler)
    root._arunika_configured = True


def get_logger(name: str) -> logging.Logger:
    _configure_logging()
    logger = logging.getLogger(name)
    return logger
