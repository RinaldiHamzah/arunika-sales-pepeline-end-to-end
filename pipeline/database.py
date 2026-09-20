"""Database connection helpers."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from pipeline.config import settings


def get_engine() -> Engine:
    settings.validate()
    # Fail clearly instead of leaving a local test or CLI process indefinitely
    # blocked when PostgreSQL is unavailable (for example before Docker starts).
    return create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,
            "options": f"-c timezone={settings.app_timezone}",
        },
    )
