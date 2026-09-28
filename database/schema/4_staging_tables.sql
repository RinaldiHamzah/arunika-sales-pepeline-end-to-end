-- Canonical sales record. Grain: one source line item before warehouse dimensions resolve.
CREATE TABLE IF NOT EXISTS staging.stg_sales (
    staging_sales_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_run_id UUID NOT NULL,
    source_name VARCHAR(30) NOT NULL CHECK (source_name IN ('SHOPEE', 'TOKOPEDIA', 'WEBSITE', 'OFFLINE_STORE')),
    source_raw_record_id BIGINT NOT NULL,
    source_order_id TEXT NOT NULL,
    source_line_number INTEGER NOT NULL DEFAULT 1 CHECK (source_line_number > 0),
    order_date DATE NOT NULL,
    product_input TEXT NOT NULL,
    mapped_sku VARCHAR(30),
    customer_nk TEXT,
    customer_name TEXT,
    city TEXT,
    payment_method TEXT,
    sale_status VARCHAR(20) NOT NULL CHECK (sale_status IN ('COMPLETED', 'CANCELLED', 'RETURNED')),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    unit_price NUMERIC(14,2) NOT NULL CHECK (unit_price >= 0),
    gross_amount NUMERIC(16,2) GENERATED ALWAYS AS (quantity * unit_price) STORED,
    source_total_amount NUMERIC(16,2),
    source_record_hash CHAR(64) NOT NULL,
    is_valid BOOLEAN NOT NULL DEFAULT TRUE,
    validation_notes JSONB NOT NULL DEFAULT '[]'::jsonb,
    transformed_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_stg_sales_source_line UNIQUE (source_name, source_order_id, source_line_number),
    CONSTRAINT chk_stg_source_total_nonnegative CHECK (source_total_amount IS NULL OR source_total_amount >= 0)
);

ALTER TABLE staging.stg_sales ADD COLUMN IF NOT EXISTS source_record_hash CHAR(64);
UPDATE staging.stg_sales SET source_record_hash = repeat('0', 64) WHERE source_record_hash IS NULL;
ALTER TABLE staging.stg_sales ALTER COLUMN source_record_hash SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_stg_sales_run ON staging.stg_sales (ingestion_run_id);
CREATE INDEX IF NOT EXISTS idx_stg_sales_date ON staging.stg_sales (order_date);
CREATE INDEX IF NOT EXISTS idx_stg_sales_mapped_sku ON staging.stg_sales (mapped_sku);
CREATE INDEX IF NOT EXISTS idx_stg_sales_valid ON staging.stg_sales (is_valid) WHERE is_valid;
