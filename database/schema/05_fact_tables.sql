-- Fact grain: one product line in one source transaction.
CREATE TABLE IF NOT EXISTS warehouse.fact_sales (
    sales_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name VARCHAR(30) NOT NULL CHECK (source_name IN ('SHOPEE', 'TOKOPEDIA', 'WEBSITE', 'OFFLINE_STORE')),
    source_order_id TEXT NOT NULL,
    source_line_number INTEGER NOT NULL DEFAULT 1 CHECK (source_line_number > 0),
    date_key INTEGER NOT NULL REFERENCES warehouse.dim_date(date_key),
    product_key BIGINT NOT NULL REFERENCES warehouse.dim_product(product_key),
    customer_key BIGINT REFERENCES warehouse.dim_customer(customer_key),
    channel_key SMALLINT NOT NULL REFERENCES warehouse.dim_channel(channel_key),
    payment_key SMALLINT REFERENCES warehouse.dim_payment(payment_key),
    sale_status VARCHAR(20) NOT NULL CHECK (sale_status IN ('COMPLETED', 'CANCELLED', 'RETURNED')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(14,2) NOT NULL CHECK (unit_price >= 0),
    gross_amount NUMERIC(16,2) NOT NULL CHECK (gross_amount >= 0),
    discount_amount NUMERIC(16,2) NOT NULL DEFAULT 0 CHECK (discount_amount >= 0),
    net_amount NUMERIC(16,2) NOT NULL CHECK (net_amount >= 0),
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_sales_business_key UNIQUE (source_name, source_order_id, source_line_number),
    CONSTRAINT chk_fact_sales_amounts CHECK (gross_amount = quantity * unit_price AND discount_amount <= gross_amount AND net_amount = gross_amount - discount_amount)
);

CREATE INDEX IF NOT EXISTS idx_fact_sales_date ON warehouse.fact_sales (date_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_product ON warehouse.fact_sales (product_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_channel_date ON warehouse.fact_sales (channel_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_completed_date ON warehouse.fact_sales (date_key) WHERE sale_status = 'COMPLETED';
