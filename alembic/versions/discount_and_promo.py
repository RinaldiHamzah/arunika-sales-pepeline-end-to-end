"""Tambahkan diskon dan kode promo pada baris transaksi."""

from alembic import op

revision = "20261109_12"
down_revision = "20261102_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table in (
        "raw.shopee_orders",
        "raw.tokopedia_transactions",
        "raw.website_transactions",
        "raw.offline_store_sales",
    ):
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS discount_amount TEXT")
        op.execute(f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS promo_code TEXT")

    op.execute("""
        ALTER TABLE staging.stg_sales
            ADD COLUMN IF NOT EXISTS discount_amount NUMERIC(16,2) NOT NULL DEFAULT 0,
            ADD COLUMN IF NOT EXISTS promo_code TEXT
    """)
    op.execute("""
        ALTER TABLE staging.stg_sales
            ADD COLUMN IF NOT EXISTS net_amount NUMERIC(16,2)
            GENERATED ALWAYS AS (quantity * unit_price - discount_amount) STORED
    """)
    op.execute("""
        DO $$ BEGIN
            ALTER TABLE staging.stg_sales
                ADD CONSTRAINT chk_stg_discount_not_above_gross
                CHECK (discount_amount >= 0 AND discount_amount <= quantity * unit_price);
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$
    """)
    op.execute("ALTER TABLE warehouse.fact_sales ADD COLUMN IF NOT EXISTS promo_code TEXT")
    op.execute("""
        CREATE OR REPLACE VIEW warehouse.v_sales_detail AS
        SELECT
            f.sales_key, f.source_name, f.source_order_id AS order_id,
            f.source_line_number AS line_number, d.full_date AS order_date,
            p.sku AS product_id, p.product_name, p.brand, p.category,
            c.channel_name, f.sale_status AS status, cu.customer_name, cu.city,
            pm.payment_method, f.quantity, f.unit_price, f.gross_amount,
            f.discount_amount, f.net_amount, f.loaded_at, f.promo_code
        FROM warehouse.fact_sales f
        JOIN warehouse.dim_date d ON d.date_key = f.date_key
        JOIN warehouse.dim_product p ON p.product_key = f.product_key
        JOIN warehouse.dim_channel c ON c.channel_key = f.channel_key
        LEFT JOIN warehouse.dim_customer cu ON cu.customer_key = f.customer_key
        LEFT JOIN warehouse.dim_payment pm ON pm.payment_key = f.payment_key
    """)


def downgrade() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM staging.stg_sales WHERE discount_amount > 0 OR promo_code IS NOT NULL)
               OR EXISTS (SELECT 1 FROM warehouse.fact_sales WHERE discount_amount > 0 OR promo_code IS NOT NULL) THEN
                RAISE EXCEPTION 'Rollback ditolak: data diskon atau promo sudah tersimpan.';
            END IF;
        END $$
    """)
    op.execute("DROP VIEW warehouse.v_sales_detail")
    op.execute("""
        CREATE VIEW warehouse.v_sales_detail AS
        SELECT
            f.sales_key, f.source_name, f.source_order_id AS order_id,
            f.source_line_number AS line_number, d.full_date AS order_date,
            p.sku AS product_id, p.product_name, p.brand, p.category,
            c.channel_name, f.sale_status AS status, cu.customer_name, cu.city,
            pm.payment_method, f.quantity, f.unit_price, f.gross_amount,
            f.discount_amount, f.net_amount, f.loaded_at
        FROM warehouse.fact_sales f
        JOIN warehouse.dim_date d ON d.date_key = f.date_key
        JOIN warehouse.dim_product p ON p.product_key = f.product_key
        JOIN warehouse.dim_channel c ON c.channel_key = f.channel_key
        LEFT JOIN warehouse.dim_customer cu ON cu.customer_key = f.customer_key
        LEFT JOIN warehouse.dim_payment pm ON pm.payment_key = f.payment_key
    """)
    op.execute("ALTER TABLE warehouse.fact_sales DROP COLUMN IF EXISTS promo_code")
    op.execute("ALTER TABLE staging.stg_sales DROP CONSTRAINT IF EXISTS chk_stg_discount_not_above_gross")
    op.execute("ALTER TABLE staging.stg_sales DROP COLUMN IF EXISTS net_amount")
    op.execute("ALTER TABLE staging.stg_sales DROP COLUMN IF EXISTS promo_code")
    op.execute("ALTER TABLE staging.stg_sales DROP COLUMN IF EXISTS discount_amount")
    for table in (
        "raw.shopee_orders",
        "raw.tokopedia_transactions",
        "raw.website_transactions",
        "raw.offline_store_sales",
    ):
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS promo_code")
        op.execute(f"ALTER TABLE {table} DROP COLUMN IF EXISTS discount_amount")
