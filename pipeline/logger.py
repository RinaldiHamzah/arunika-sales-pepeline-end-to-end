"""Consistent console logging for pipeline modules."""
import logging
from pipeline.config import settings


def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=settings.log_level.upper(),
            format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        )
    return logger
