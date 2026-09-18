"""Restrict public database access and application role privileges."""
from alembic import op


revision = "20260917_02"
down_revision = "20260917_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("REVOKE CONNECT ON DATABASE ecommerce_sales FROM PUBLIC")
    op.execute("GRANT CONNECT ON DATABASE ecommerce_sales TO CURRENT_USER")
    # Role privilege changes require a separate cluster administrator. The
    # application role is intentionally managed outside transactional Alembic.


def downgrade() -> None:
    # Privilege elevation is intentionally never automated on downgrade.
    pass
