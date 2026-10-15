"""Batasi akses publik ke basis data dan hak akses peran aplikasi."""
from alembic import op


revision = "20260917_02"
down_revision = "20260917_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
    op.execute("""
        DO $$ BEGIN
            EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', current_database());
            EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), current_user);
        END $$;
    """)
    # Perubahan hak akses peran memerlukan administrator klaster tersendiri.
    # Peran aplikasi sengaja dikelola di luar transaksi Alembic.


def downgrade() -> None:
    # Peningkatan hak akses tidak pernah dijalankan otomatis saat downgrade.
    pass
