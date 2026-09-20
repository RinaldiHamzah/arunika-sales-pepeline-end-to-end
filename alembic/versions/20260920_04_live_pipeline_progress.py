"""Record the currently executing pipeline stage for live UI progress."""

from alembic import op


revision = "20260920_04"
down_revision = "20260917_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE audit.pipeline_runs
            ADD COLUMN IF NOT EXISTS current_stage VARCHAR(50),
            ADD COLUMN IF NOT EXISTS current_stage_started_at TIMESTAMPTZ
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE audit.pipeline_runs
            DROP COLUMN IF EXISTS current_stage_started_at,
            DROP COLUMN IF EXISTS current_stage
    """)
