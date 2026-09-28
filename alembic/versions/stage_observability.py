"""Add per-stage observability records."""
from alembic import op


revision = "20260917_03"
down_revision = "20260917_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.pipeline_stage_runs (
            stage_run_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id) ON DELETE CASCADE,
            stage_name VARCHAR(50) NOT NULL,
            status VARCHAR(20) NOT NULL CHECK (status IN ('SUCCESS', 'FAILED')),
            started_at TIMESTAMPTZ NOT NULL,
            ended_at TIMESTAMPTZ NOT NULL,
            duration_seconds NUMERIC(12,3) NOT NULL CHECK (duration_seconds >= 0),
            records_processed INTEGER NOT NULL DEFAULT 0 CHECK (records_processed >= 0),
            error_message TEXT,
            CONSTRAINT chk_stage_run_end CHECK (ended_at >= started_at)
        )
    """)
    op.execute("""
        CREATE INDEX IF NOT EXISTS idx_audit_stage_runs_run
        ON audit.pipeline_stage_runs (run_id, started_at)
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS audit.pipeline_stage_runs")
