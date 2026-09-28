"""Normalize legacy placeholder text in the customer city dimension."""

from alembic import op


revision = "20260920_05"
down_revision = "20260920_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # City is optional.  A textual NaN is a legacy source marker, not a city.
    # Keep it NULL so analytics can present one explicit "Unknown city" bucket.
    op.execute("""
        UPDATE warehouse.dim_customer
        SET city = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE city IS NOT NULL
          AND LOWER(BTRIM(city)) IN ('', 'nan', 'none', 'null', 'n/a', 'na')
    """)


def downgrade() -> None:
    # The original placeholder does not carry recoverable geographic information.
    pass
