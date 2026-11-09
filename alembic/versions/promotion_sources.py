"""Tambahkan sumber master promo dan pemakaian promo pada order."""

from alembic import op

revision = "20261109_13"
down_revision = "20261109_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS raw.promo_master (
            raw_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ingestion_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
            source_file_name TEXT NOT NULL,
            source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            promo_code TEXT, promo_name TEXT, discount_type TEXT, discount_value TEXT,
            start_date TEXT, end_date TEXT, status TEXT, source_payload JSONB NOT NULL,
            CONSTRAINT uq_raw_promo_master_file_row
                UNIQUE (ingestion_run_id, source_file_name, source_row_number)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS raw.order_promotions (
            raw_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ingestion_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
            source_file_name TEXT NOT NULL,
            source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_name TEXT, order_id TEXT, promo_code TEXT, discount_amount TEXT,
            source_payload JSONB NOT NULL,
            CONSTRAINT uq_raw_order_promotions_file_row
                UNIQUE (ingestion_run_id, source_file_name, source_row_number)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS warehouse.dim_promotion (
            promo_code TEXT PRIMARY KEY,
            promo_name TEXT NOT NULL,
            discount_type TEXT NOT NULL CHECK (discount_type IN ('fixed', 'percentage')),
            discount_value NUMERIC(16,2) NOT NULL CHECK (discount_value > 0),
            start_date DATE NOT NULL,
            end_date DATE NOT NULL CHECK (end_date >= start_date),
            status TEXT NOT NULL CHECK (status IN ('active', 'expired', 'paused')),
            is_active BOOLEAN NOT NULL DEFAULT TRUE,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM warehouse.fact_sales WHERE promo_code IS NOT NULL) THEN
                RAISE EXCEPTION 'Rollback ditolak: fact_sales masih merujuk pada kode promo.';
            END IF;
        END $$
    """)
    op.execute("DROP TABLE IF EXISTS warehouse.dim_promotion")
    op.execute("DROP TABLE IF EXISTS raw.order_promotions")
    op.execute("DROP TABLE IF EXISTS raw.promo_master")
