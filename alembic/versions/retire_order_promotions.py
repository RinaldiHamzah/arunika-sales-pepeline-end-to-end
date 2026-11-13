"""Retire unused raw order-promotions source table."""

from alembic import op

revision = "20261114_20"
down_revision = "20261113_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve legacy payloads: never drop the table automatically while it has rows.
    op.execute("""
        DO $$
        DECLARE
            legacy_rows BIGINT;
        BEGIN
            IF to_regclass('raw.order_promotions') IS NOT NULL THEN
                EXECUTE 'SELECT COUNT(*) FROM raw.order_promotions' INTO legacy_rows;
                IF legacy_rows > 0 THEN
                    RAISE EXCEPTION
                        'Cannot retire raw.order_promotions: table contains % rows. Export/archive the data, then rerun the migration.',
                        legacy_rows;
                END IF;
                DROP TABLE raw.order_promotions;
            END IF;
        END $$;
    """)


def downgrade() -> None:
    # Schema rollback restores an empty legacy table; retired data is never recreated.
    op.execute("""
        CREATE TABLE IF NOT EXISTS raw.order_promotions (
            raw_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ingestion_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
            source_file_name TEXT NOT NULL,
            source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_name TEXT,
            order_id TEXT,
            promo_code TEXT,
            discount_amount TEXT,
            source_payload JSONB NOT NULL,
            CONSTRAINT uq_raw_order_promotions_file_row
                UNIQUE (ingestion_run_id, source_file_name, source_row_number)
        )
    """)
