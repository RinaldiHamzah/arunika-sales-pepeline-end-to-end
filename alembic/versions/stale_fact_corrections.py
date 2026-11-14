"""Track rejected corrections that leave the last valid sales fact stale."""

from alembic import op

revision = "20261114_21"
down_revision = "20261114_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.stale_fact_corrections (
            source_name VARCHAR(30) NOT NULL,
            source_order_id TEXT NOT NULL,
            source_line_number INTEGER NOT NULL CHECK (source_line_number > 0),
            rejected_run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
            source_row_number INTEGER,
            rejection_reason TEXT NOT NULL,
            rejected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMPTZ,
            resolved_run_id UUID REFERENCES audit.pipeline_runs(run_id),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (source_name, source_order_id, source_line_number),
            CHECK ((resolved_at IS NULL) = (resolved_run_id IS NULL))
        );
        CREATE INDEX IF NOT EXISTS idx_stale_fact_corrections_run
            ON audit.stale_fact_corrections (rejected_run_id);
        CREATE INDEX IF NOT EXISTS idx_stale_fact_corrections_unresolved
            ON audit.stale_fact_corrections (source_name, rejected_at DESC)
            WHERE resolved_at IS NULL;
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit.stale_fact_corrections")
