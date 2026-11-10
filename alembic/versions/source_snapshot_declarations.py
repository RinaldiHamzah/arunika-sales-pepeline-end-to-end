"""Simpan deklarasi cakupan ingestion untuk audit rekonsiliasi sumber."""

from alembic import op

revision = "20261110_17"
down_revision = "20261110_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE audit.source_reconciliations ADD COLUMN IF NOT EXISTS ingestion_mode VARCHAR(30) NOT NULL DEFAULT 'INCREMENTAL_BATCH'")
    op.execute("ALTER TABLE audit.source_reconciliations ADD COLUMN IF NOT EXISTS snapshot_scope TEXT")
    op.execute("ALTER TABLE audit.source_reconciliations ADD COLUMN IF NOT EXISTS snapshot_timestamp TIMESTAMPTZ")
    op.execute("ALTER TABLE audit.source_reconciliations ADD COLUMN IF NOT EXISTS snapshot_completeness VARCHAR(20) NOT NULL DEFAULT 'UNKNOWN'")


def downgrade() -> None:
    op.execute("ALTER TABLE audit.source_reconciliations DROP COLUMN IF EXISTS snapshot_completeness")
    op.execute("ALTER TABLE audit.source_reconciliations DROP COLUMN IF EXISTS snapshot_timestamp")
    op.execute("ALTER TABLE audit.source_reconciliations DROP COLUMN IF EXISTS snapshot_scope")
    op.execute("ALTER TABLE audit.source_reconciliations DROP COLUMN IF EXISTS ingestion_mode")
