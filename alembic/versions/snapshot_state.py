"""Store the last successful source snapshot and correlate Airflow runs."""
from alembic import op

revision = "20260920_06"
down_revision = "20260920_05"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
CREATE TABLE IF NOT EXISTS audit.source_snapshots (
    pipeline_name VARCHAR(100) NOT NULL,
    source_name VARCHAR(30) NOT NULL,
    file_checksum_sha256 CHAR(64) NOT NULL,
    payload_hashes JSONB NOT NULL CHECK (jsonb_typeof(payload_hashes) = 'array'),
    run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (pipeline_name, source_name)
);
ALTER TABLE audit.pipeline_runs ADD COLUMN IF NOT EXISTS orchestration_run_id TEXT;
CREATE INDEX IF NOT EXISTS idx_runs_orchestration
    ON audit.pipeline_runs (pipeline_name, orchestration_run_id, started_at DESC);
    """)


def downgrade():
    # Keep additive audit history. No destructive rollback.
    pass
