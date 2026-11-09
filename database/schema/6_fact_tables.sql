-- Grain fact: satu baris produk dalam satu transaksi sumber.
CREATE TABLE IF NOT EXISTS warehouse.fact_sales (
    sales_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name VARCHAR(30) NOT NULL CHECK (source_name IN ('SHOPEE', 'TOKOPEDIA', 'WEBSITE', 'OFFLINE_STORE')),
    source_order_id TEXT NOT NULL,
    source_line_number INTEGER NOT NULL CHECK (source_line_number > 0),
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
    promo_code TEXT,
    source_record_hash CHAR(64) NOT NULL,
    is_source_active BOOLEAN NOT NULL DEFAULT TRUE,
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_sales_business_key UNIQUE (source_name, source_order_id, source_line_number),
    CONSTRAINT chk_fact_sales_amounts CHECK (gross_amount = quantity * unit_price AND discount_amount <= gross_amount AND net_amount = gross_amount - discount_amount)
);

ALTER TABLE warehouse.fact_sales ADD COLUMN IF NOT EXISTS source_record_hash CHAR(64);
UPDATE warehouse.fact_sales SET source_record_hash = repeat('0', 64) WHERE source_record_hash IS NULL;
ALTER TABLE warehouse.fact_sales ALTER COLUMN source_record_hash SET NOT NULL;
ALTER TABLE warehouse.fact_sales ADD COLUMN IF NOT EXISTS is_source_active BOOLEAN NOT NULL DEFAULT TRUE;

CREATE INDEX IF NOT EXISTS idx_fact_sales_date ON warehouse.fact_sales (date_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_product ON warehouse.fact_sales (product_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_channel_date ON warehouse.fact_sales (channel_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_completed_date ON warehouse.fact_sales (date_key) WHERE sale_status = 'COMPLETED';

-- Grain retur: satu baris item pada satu pengajuan/kejadian retur.
CREATE TABLE IF NOT EXISTS warehouse.fact_returns (
    return_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    source_name VARCHAR(30) NOT NULL CHECK (source_name IN ('SHOPEE', 'TOKOPEDIA', 'WEBSITE', 'OFFLINE_STORE')),
    return_id TEXT NOT NULL,
    return_line_number INTEGER NOT NULL CHECK (return_line_number > 0),
    source_order_id TEXT NOT NULL,
    source_line_number INTEGER NOT NULL CHECK (source_line_number > 0),
    return_date DATE NOT NULL,
    return_reason TEXT NOT NULL,
    return_status VARCHAR(20) NOT NULL CHECK (return_status IN ('PENDING', 'APPROVED', 'REJECTED', 'PROCESSED')),
    quantity_returned INTEGER NOT NULL CHECK (quantity_returned > 0),
    refund_amount NUMERIC(16,2),
    refund_status VARCHAR(20) NOT NULL CHECK (refund_status IN ('NOT_APPLICABLE', 'PENDING', 'PROCESSED', 'FAILED')),
    source_raw_record_id BIGINT NOT NULL REFERENCES raw.return_events(raw_record_id),
    source_record_hash CHAR(64) NOT NULL,
    ingestion_run_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_returns_event UNIQUE (source_name, return_id, return_line_number),
    CONSTRAINT fk_fact_returns_sales_line FOREIGN KEY (source_name, source_order_id, source_line_number)
        REFERENCES warehouse.fact_sales (source_name, source_order_id, source_line_number),
    CONSTRAINT chk_fact_returns_refund_amount CHECK (
        (refund_status = 'PROCESSED' AND refund_amount IS NOT NULL AND refund_amount >= 0)
        OR (refund_status <> 'PROCESSED' AND refund_amount IS NULL)
    ),
    CONSTRAINT chk_fact_returns_rejected_no_refund CHECK (
        return_status NOT IN ('PENDING', 'REJECTED') OR refund_status <> 'PROCESSED'
    )
);

CREATE INDEX IF NOT EXISTS idx_fact_returns_sales_line
    ON warehouse.fact_returns (source_name, source_order_id, source_line_number);
CREATE INDEX IF NOT EXISTS idx_fact_returns_date_status
    ON warehouse.fact_returns (return_date, return_status, refund_status);
