"""Selaraskan KPI penjualan dengan unit retur dan refund yang telah diproses."""

from pathlib import Path

from alembic import op

revision = "20261110_16"
down_revision = "20261109_15"
branch_labels = None
depends_on = None

ROOT = Path(__file__).resolve().parents[2]
NEW_VIEWS = ROOT / "database" / "schema" / "9_return_adjusted_kpis.sql"
OLD_VIEWS = ROOT / "database" / "schema" / "8_analytics_views.sql"


def _execute_file(path: Path) -> None:
    """Eksekusi satu pernyataan SQL per panggilan, sesuai protokol PostgreSQL."""
    statement = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            statement.append(line)
        if line.rstrip().endswith(";"):
            op.execute("\n".join(statement))
            statement = []
    if statement:
        raise ValueError(f"File SQL tidak berakhir dengan titik koma: {path}")


def _drop_views() -> None:
    for name in (
        "warehouse.v_sales_status_kpi",
        "warehouse.v_top_product_kpi",
        "warehouse.v_sales_channel_kpi",
        "warehouse.v_sales_monthly_kpi",
        "warehouse.v_sales_kpi",
        "warehouse.v_sales_by_product",
        "warehouse.v_sales_by_channel",
        "warehouse.v_sales_by_month",
        "warehouse.v_sales_detail",
    ):
        op.execute(f"DROP VIEW IF EXISTS {name}")


def upgrade() -> None:
    _drop_views()
    _execute_file(NEW_VIEWS)


def downgrade() -> None:
    _drop_views()
    _execute_file(OLD_VIEWS)
