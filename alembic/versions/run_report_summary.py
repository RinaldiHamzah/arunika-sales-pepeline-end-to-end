"""Store a consistent Raw, Quality/Staging, and Warehouse run summary."""

from alembic import op

revision = "20260926_10"
down_revision = "20260925_09"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        ALTER TABLE audit.pipeline_runs
        ADD COLUMN IF NOT EXISTS report_summary JSONB;
        """
    )


def downgrade():
    op.execute("ALTER TABLE audit.pipeline_runs DROP COLUMN IF EXISTS report_summary;")
