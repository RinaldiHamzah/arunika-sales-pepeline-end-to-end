"""Tambahkan Raw dan Warehouse untuk kejadian retur serta refund."""

from alembic import op

revision = "20261109_14"
down_revision = "20261109_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS raw.return_events (
            raw_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            ingestion_run_id UUID NOT NULL,
            source_file_name TEXT NOT NULL,
            source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
            ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            source_name TEXT, return_id TEXT, return_line_number TEXT,
            order_id TEXT, order_line_number TEXT, return_date TEXT,
            return_reason TEXT, return_status TEXT, quantity_returned TEXT,
            refund_amount TEXT, refund_status TEXT, source_payload JSONB NOT NULL,
            CONSTRAINT fk_raw_return_events_run
                FOREIGN KEY (ingestion_run_id) REFERENCES audit.pipeline_runs(run_id),
            CONSTRAINT uq_raw_return_file_row
                UNIQUE (ingestion_run_id, source_file_name, source_row_number)
        )
    """)
    op.execute("""
        CREATE TABLE IF NOT EXISTS warehouse.fact_returns (
            return_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            source_name VARCHAR(30) NOT NULL
                CHECK (source_name IN ('SHOPEE', 'TOKOPEDIA', 'WEBSITE', 'OFFLINE_STORE')),
            return_id TEXT NOT NULL,
            return_line_number INTEGER NOT NULL CHECK (return_line_number > 0),
            source_order_id TEXT NOT NULL,
            source_line_number INTEGER NOT NULL CHECK (source_line_number > 0),
            return_date DATE NOT NULL,
            return_reason TEXT NOT NULL,
            return_status VARCHAR(20) NOT NULL
                CHECK (return_status IN ('PENDING', 'APPROVED', 'REJECTED', 'PROCESSED')),
            quantity_returned INTEGER NOT NULL CHECK (quantity_returned > 0),
            refund_amount NUMERIC(16,2),
            refund_status VARCHAR(20) NOT NULL
                CHECK (refund_status IN ('NOT_APPLICABLE', 'PENDING', 'PROCESSED', 'FAILED')),
            source_raw_record_id BIGINT NOT NULL REFERENCES raw.return_events(raw_record_id),
            source_record_hash CHAR(64) NOT NULL,
            ingestion_run_id UUID NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            CONSTRAINT uq_fact_returns_event UNIQUE (source_name, return_id, return_line_number),
            CONSTRAINT fk_fact_returns_run
                FOREIGN KEY (ingestion_run_id) REFERENCES audit.pipeline_runs(run_id),
            CONSTRAINT fk_fact_returns_sales_line
                FOREIGN KEY (source_name, source_order_id, source_line_number)
                REFERENCES warehouse.fact_sales (source_name, source_order_id, source_line_number),
            CONSTRAINT chk_fact_returns_refund_amount CHECK (
                (refund_status = 'PROCESSED' AND refund_amount IS NOT NULL AND refund_amount >= 0)
                OR (refund_status <> 'PROCESSED' AND refund_amount IS NULL)
            ),
            CONSTRAINT chk_fact_returns_rejected_no_refund CHECK (
                return_status NOT IN ('PENDING', 'REJECTED') OR refund_status <> 'PROCESSED'
            )
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_fact_returns_sales_line
        ON warehouse.fact_returns (source_name, source_order_id, source_line_number)
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_fact_returns_date_status
        ON warehouse.fact_returns (return_date, return_status, refund_status)
    """)
    op.execute("""
        CREATE OR REPLACE VIEW warehouse.v_return_refund_kpi AS
        SELECT
            date_trunc('month', return_date)::DATE AS return_month,
            source_name,
            COUNT(DISTINCT return_id) AS return_requests,
            COUNT(*) AS return_line_events,
            COUNT(*) FILTER (WHERE return_status IN ('APPROVED', 'PROCESSED')) AS approved_return_lines,
            COALESCE(
                SUM(quantity_returned) FILTER (WHERE return_status IN ('APPROVED', 'PROCESSED')),
                0
            ) AS approved_return_units,
            COALESCE(
                SUM(refund_amount) FILTER (WHERE refund_status = 'PROCESSED'),
                0
            ) AS processed_refund_amount
        FROM warehouse.fact_returns
        GROUP BY date_trunc('month', return_date)::DATE, source_name
    """)


def downgrade() -> None:
    op.execute("DROP VIEW IF EXISTS warehouse.v_return_refund_kpi")
    op.execute("DROP TABLE IF EXISTS warehouse.fact_returns")
    op.execute("DROP TABLE IF EXISTS raw.return_events")
