"""Run extraction and raw ingestion: python -m pipeline.runner."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import text

from pipeline.database import get_engine
from pipeline.extract.sources import extract_all
from pipeline.load.raw_loader import load_raw
from pipeline.logger import get_logger

LOGGER = get_logger(__name__)
SOURCE_DIR = Path(__file__).resolve().parents[1] / "data" / "source"


def run() -> None:
    sources = extract_all(SOURCE_DIR)
    extracted_count = sum(len(source.frame) for source in sources)
    engine = get_engine()

    with engine.begin() as connection:
        run_id = connection.execute(text("""
            INSERT INTO audit.pipeline_runs (pipeline_name, status, extracted_records)
            VALUES (:pipeline_name, 'RUNNING', :extracted_records)
            RETURNING run_id
        """), {"pipeline_name": "ecommerce_sales_pipeline", "extracted_records": extracted_count}).scalar_one()

    try:
        with engine.begin() as connection:
            loaded_count = sum(load_raw(connection, run_id, source) for source in sources)
            connection.execute(text("""
                UPDATE audit.pipeline_runs
                SET status = 'SUCCESS', ended_at = CURRENT_TIMESTAMP, loaded_records = :loaded_records
                WHERE run_id = :run_id
            """), {"run_id": run_id, "loaded_records": loaded_count})
        LOGGER.info("Raw ingestion succeeded: run_id=%s extracted=%s loaded=%s", run_id, extracted_count, loaded_count)
    except Exception as error:
        with engine.begin() as connection:
            connection.execute(text("""
                UPDATE audit.pipeline_runs
                SET status = 'FAILED', ended_at = CURRENT_TIMESTAMP, error_message = :error_message
                WHERE run_id = :run_id
            """), {"run_id": run_id, "error_message": str(error)})
        LOGGER.exception("Raw ingestion failed: run_id=%s", run_id)
        raise


if __name__ == "__main__":
    run()
