"""Consistent console logging for pipeline modules."""
import logging
import json
import os
from datetime import datetime, timezone
from pipeline.config import settings


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logging.getLogger().handlers:
        if os.getenv("LOG_FORMAT", "text").lower() == "json":
            class JsonFormatter(logging.Formatter):
                def format(self, record):
                    return json.dumps({
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "level": record.levelname, "logger": record.name,
                        "message": record.getMessage(),
                    }, ensure_ascii=False)
            handler = logging.StreamHandler()
            handler.setFormatter(JsonFormatter())
            root = logging.getLogger()
            root.setLevel(settings.log_level.upper())
            root.addHandler(handler)
        else:
            logging.basicConfig(
                level=settings.log_level.upper(),
                format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            )
    return logger
