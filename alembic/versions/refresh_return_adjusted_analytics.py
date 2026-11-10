"""Bangun ulang view KPI setelah definisi view tidak selaras dengan revisi Alembic."""

from pathlib import Path

from alembic import op

revision = "20261111_18"
down_revision = "20261110_17"
branch_labels = None
depends_on = None

ROOT = Path(__file__).resolve().parents[2]
NEW_VIEWS = ROOT / "database" / "schema" / "9_return_adjusted_kpis.sql"
OLD_VIEWS = ROOT / "database" / "schema" / "8_analytics_views.sql"

VIEW_NAMES = (
    "warehouse.v_sales_status_kpi",
    "warehouse.v_top_product_kpi",
    "warehouse.v_sales_channel_kpi",
    "warehouse.v_sales_monthly_kpi",
    "warehouse.v_sales_kpi",
    "warehouse.v_sales_by_product",
    "warehouse.v_sales_by_channel",
    "warehouse.v_sales_by_month",
    "warehouse.v_sales_detail",
)


def _drop_views() -> None:
    for name in VIEW_NAMES:
        op.execute(f"DROP VIEW IF EXISTS {name}")


def _execute_file(path: Path) -> None:
    """Jalankan setiap pernyataan dalam berkas SQL secara terpisah."""
    statement = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            statement.append(line)
        if line.rstrip().endswith(";"):
            op.execute("\n".join(statement))
            statement = []
    if statement:
        raise ValueError(f"Pernyataan SQL terakhir tidak diakhiri titik koma: {path}")


def upgrade() -> None:
    _drop_views()
    _execute_file(NEW_VIEWS)


def downgrade() -> None:
    _drop_views()
    _execute_file(OLD_VIEWS)
