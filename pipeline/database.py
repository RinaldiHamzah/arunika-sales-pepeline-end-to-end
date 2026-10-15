"""Koneksi basis data."""

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine

from pipeline.config import settings


def get_engine() -> Engine:
    settings.validate()
    # Tampilkan kegagalan dengan jelas agar proses tes lokal atau CLI tidak
    # tertahan tanpa batas saat PostgreSQL belum tersedia, misalnya sebelum Docker aktif.
    return create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        connect_args={
            "connect_timeout": 10,
            "options": f"-c timezone={settings.app_timezone}",
        },
    )
