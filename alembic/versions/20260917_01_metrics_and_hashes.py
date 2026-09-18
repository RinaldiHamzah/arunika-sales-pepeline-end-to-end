"""Add operational audit metrics and incremental row hashes.

This revision is safe on both a fresh SQL-init database and an older volume.
"""
from alembic import op


revision = "20260917_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE audit.pipeline_runs
            ADD COLUMN IF NOT EXISTS duration_seconds NUMERIC(12,3),
            ADD COLUMN IF NOT EXISTS validated_records INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS rejected_records INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS incremental_records INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS staged_records INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS dimension_records INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS fact_inserted_records INTEGER NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS fact_skipped_records INTEGER NOT NULL DEFAULT 0
    """)
    op.execute("""
        ALTER TABLE staging.stg_sales ADD COLUMN IF NOT EXISTS source_record_hash CHAR(64)
    """)
    op.execute("""
        UPDATE staging.stg_sales SET source_record_hash = repeat('0', 64)
        WHERE source_record_hash IS NULL
    """)
    op.execute("ALTER TABLE staging.stg_sales ALTER COLUMN source_record_hash SET NOT NULL")
    op.execute("ALTER TABLE warehouse.fact_sales ADD COLUMN IF NOT EXISTS source_record_hash CHAR(64)")
    op.execute("""
        UPDATE warehouse.fact_sales SET source_record_hash = repeat('0', 64)
        WHERE source_record_hash IS NULL
    """)
    op.execute("ALTER TABLE warehouse.fact_sales ALTER COLUMN source_record_hash SET NOT NULL")
    op.execute("""
        ALTER TABLE warehouse.fact_sales
            ADD COLUMN IF NOT EXISTS is_source_active BOOLEAN NOT NULL DEFAULT TRUE
    """)


def downgrade() -> None:
    # Metrics are additive and shared with audit history; keep them on downgrade.
    pass
