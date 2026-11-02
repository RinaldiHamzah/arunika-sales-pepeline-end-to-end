"""Tambahkan identitas item sumber tanpa mengubah record historis."""

from sqlalchemy import text

from alembic import op

revision = "20261102_11"
down_revision = "20260926_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE raw.shopee_orders ADD COLUMN IF NOT EXISTS order_line_id TEXT")
    op.execute("ALTER TABLE raw.tokopedia_transactions ADD COLUMN IF NOT EXISTS item_sequence TEXT")
    op.execute("ALTER TABLE raw.website_transactions ADD COLUMN IF NOT EXISTS line_item_no TEXT")
    op.execute("ALTER TABLE raw.offline_store_sales ADD COLUMN IF NOT EXISTS receipt_line_no TEXT")
    op.execute("ALTER TABLE audit.rejected_records ADD COLUMN IF NOT EXISTS source_line_number INTEGER")
    op.execute("ALTER TABLE staging.stg_sales ALTER COLUMN source_line_number DROP DEFAULT")
    op.execute("ALTER TABLE warehouse.fact_sales ALTER COLUMN source_line_number DROP DEFAULT")


def downgrade() -> None:
    """Tolak rollback pada data multi-item; jangan hapus bukti Raw/Audit historis."""
    has_multiline = (
        op.get_bind()
        .execute(
            text("""
            SELECT EXISTS (
                SELECT 1 FROM staging.stg_sales WHERE source_line_number > 1
                UNION ALL
                SELECT 1 FROM warehouse.fact_sales WHERE source_line_number > 1
            )
        """)
        )
        .scalar_one()
    )
    if has_multiline:
        raise RuntimeError(
            "Rollback ditolak: Staging/Fact sudah memiliki order multi-item; lakukan rekonsiliasi dahulu."
        )
    op.execute("ALTER TABLE staging.stg_sales ALTER COLUMN source_line_number SET DEFAULT 1")
    op.execute("ALTER TABLE warehouse.fact_sales ALTER COLUMN source_line_number SET DEFAULT 1")
