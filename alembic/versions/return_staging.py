"""Tambahkan lapisan staging kanonis untuk event return/refund."""

from alembic import op

revision = "20261113_19"
down_revision = "20261111_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS staging.stg_returns (
            staging_return_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ingestion_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
            source_name VARCHAR(30) NOT NULL CHECK
                (source_name IN ('SHOPEE', 'TOKOPEDIA', 'WEBSITE', 'OFFLINE_STORE')),
            source_raw_record_id BIGINT NOT NULL REFERENCES raw.return_events(raw_record_id),
            source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
            return_id TEXT NOT NULL,
            return_line_number INTEGER NOT NULL CHECK (return_line_number > 0),
            source_order_id TEXT NOT NULL,
            source_line_number INTEGER NOT NULL CHECK (source_line_number > 0),
            return_date DATE NOT NULL,
            return_reason TEXT NOT NULL,
            return_status VARCHAR(20) NOT NULL CHECK
                (return_status IN ('PENDING', 'APPROVED', 'REJECTED', 'PROCESSED')),
            quantity_returned INTEGER NOT NULL CHECK (quantity_returned > 0),
            refund_amount NUMERIC(16,2),
            refund_status VARCHAR(20) NOT NULL CHECK
                (refund_status IN ('NOT_APPLICABLE', 'PENDING', 'PROCESSED', 'FAILED')),
            source_record_hash CHAR(64) NOT NULL,
            is_valid BOOLEAN NOT NULL DEFAULT TRUE CHECK (is_valid),
            validation_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
            transformed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_stg_returns_event UNIQUE (source_name, return_id, return_line_number),
            CONSTRAINT chk_stg_returns_refund_amount CHECK (
                (refund_status = 'PROCESSED' AND refund_amount IS NOT NULL AND refund_amount >= 0)
                OR (refund_status <> 'PROCESSED' AND refund_amount IS NULL)
            ),
            CONSTRAINT chk_stg_returns_rejected_no_refund CHECK (
                return_status NOT IN ('PENDING', 'REJECTED') OR refund_status <> 'PROCESSED'
            )
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_stg_returns_run ON staging.stg_returns (ingestion_run_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_stg_returns_order ON staging.stg_returns (source_name, source_order_id, source_line_number)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS staging.stg_returns")
