"""Explain pre-validation skips without inventing metrics for historical runs."""
from alembic import op

revision = "20260922_07"
down_revision = "20260920_06"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("""
ALTER TABLE audit.source_snapshots ADD COLUMN IF NOT EXISTS source_records BIGINT CHECK (source_records >= 0);
ALTER TABLE audit.pipeline_runs
    ADD COLUMN IF NOT EXISTS source_records BIGINT CHECK (source_records >= 0),
    ADD COLUMN IF NOT EXISTS skipped_unchanged_records BIGINT CHECK (skipped_unchanged_records >= 0),
    ADD COLUMN IF NOT EXISTS source_metrics JSONB,
    ADD COLUMN IF NOT EXISTS outcome_message TEXT;
    """)


def downgrade():
    # Keep additive audit history.
    pass
