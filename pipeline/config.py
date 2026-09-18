"""Centralized, environment-driven pipeline configuration."""
from dataclasses import dataclass
import os
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    pipeline_name: str = os.getenv("PIPELINE_NAME", "ecommerce_sales_pipeline")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    database_url: str = os.getenv("DATABASE_URL", "")
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5433"))
    postgres_db: str = os.getenv("POSTGRES_DB", "ecommerce_sales")
    postgres_user: str = os.getenv("POSTGRES_USER", "ecommerce_user")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "change_me")
    flask_debug: bool = os.getenv("FLASK_DEBUG", "0").lower() in {"1", "true", "yes"}

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url or f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

    def validate(self) -> None:
        """Reject unsafe/incomplete connection settings before opening a database."""
        if not self.database_url and (not self.postgres_password or self.postgres_password == "change_me"):
            raise ValueError("POSTGRES_PASSWORD must be set to a non-default secret")
        if not self.postgres_db or not self.postgres_user:
            raise ValueError("POSTGRES_DB and POSTGRES_USER are required")
        if not 1 <= self.postgres_port <= 65535:
            raise ValueError("POSTGRES_PORT must be between 1 and 65535")
        if self.database_url and urlparse(self.database_url).scheme not in {"postgresql", "postgresql+psycopg"}:
            raise ValueError("DATABASE_URL must use the PostgreSQL psycopg driver")

settings = Settings()
