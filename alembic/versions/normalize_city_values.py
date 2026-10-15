"""Normalisasi teks penanda lama pada dimensi kota pelanggan."""

from alembic import op


revision = "20260920_05"
down_revision = "20260920_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Kota bersifat opsional. Teks NaN adalah penanda lama dari sumber, bukan nama kota.
    # Simpan sebagai NULL agar analitik dapat menampilkan satu kelompok "Kota tidak diketahui".
    op.execute("""
        UPDATE warehouse.dim_customer
        SET city = NULL,
            updated_at = CURRENT_TIMESTAMP
        WHERE city IS NOT NULL
          AND LOWER(BTRIM(city)) IN ('', 'nan', 'none', 'null', 'n/a', 'na')
    """)


def downgrade() -> None:
    # Penanda lama tersebut tidak memuat informasi geografis yang dapat dipulihkan.
    pass
