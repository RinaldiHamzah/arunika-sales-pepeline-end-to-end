"""Database connection helpers."""
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from pipeline.config import settings


def get_engine() -> Engine:
    settings.validate()
    return create_engine(settings.sqlalchemy_url, pool_pre_ping=True)
