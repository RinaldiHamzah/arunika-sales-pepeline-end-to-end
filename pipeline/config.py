"""Centralized, environment-driven pipeline configuration."""
from dataclasses import dataclass
import os
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Settings:
    pipeline_name: str = os.getenv("PIPELINE_NAME", "ecommerce_sales_pipeline")
    log_level: str = os.getenv("LOG_LEVEL", "INFO")
    database_url: str = os.getenv("DATABASE_URL", "")
    postgres_host: str = os.getenv("POSTGRES_HOST", "localhost")
    postgres_port: int = int(os.getenv("POSTGRES_PORT", "5432"))
    postgres_db: str = os.getenv("POSTGRES_DB", "ecommerce_dw")
    postgres_user: str = os.getenv("POSTGRES_USER", "ecommerce_user")
    postgres_password: str = os.getenv("POSTGRES_PASSWORD", "change_me")

    @property
    def sqlalchemy_url(self) -> str:
        return self.database_url or f"postgresql+psycopg2://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"

settings = Settings()
