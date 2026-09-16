-- Raw tables retain source-specific fields and allow bad values for data-quality analysis.
-- Business IDs are deliberately not unique here: duplicate source records must remain observable.

CREATE TABLE IF NOT EXISTS raw.shopee_orders (
    raw_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_run_id UUID NOT NULL, source_file_name TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    order_id TEXT, order_date TEXT, product_name TEXT, qty TEXT, unit_price TEXT,
    customer_id TEXT, customer_name TEXT, customer_city TEXT, payment_method TEXT, status TEXT,
    source_payload JSONB NOT NULL,
    CONSTRAINT uq_raw_shopee_file_row UNIQUE (ingestion_run_id, source_file_name, source_row_number)
);

CREATE TABLE IF NOT EXISTS raw.tokopedia_transactions (
    raw_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_run_id UUID NOT NULL, source_file_name TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    transaction_id TEXT, transaction_date TEXT, item_name TEXT, quantity TEXT, price TEXT,
    buyer_name TEXT, city TEXT, payment TEXT, status TEXT,
    source_payload JSONB NOT NULL,
    CONSTRAINT uq_raw_tokopedia_file_row UNIQUE (ingestion_run_id, source_file_name, source_row_number)
);

CREATE TABLE IF NOT EXISTS raw.website_transactions (
    raw_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_run_id UUID NOT NULL, source_file_name TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    invoice_no TEXT, created_at TEXT, product_identifier TEXT, quantity TEXT, unit_price TEXT,
    total_amount TEXT, customer_email TEXT, status TEXT, source_payload JSONB NOT NULL,
    CONSTRAINT uq_raw_website_file_row UNIQUE (ingestion_run_id, source_file_name, source_row_number)
);

CREATE TABLE IF NOT EXISTS raw.offline_store_sales (
    raw_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_run_id UUID NOT NULL, source_file_name TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    pos_receipt_no TEXT, sold_at TEXT, item_description TEXT, units TEXT, item_price TEXT,
    store_name TEXT, store_city TEXT, payment_type TEXT, status TEXT, source_payload JSONB NOT NULL,
    CONSTRAINT uq_raw_offline_file_row UNIQUE (ingestion_run_id, source_file_name, source_row_number)
);

CREATE TABLE IF NOT EXISTS raw.product_master (
    raw_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ingestion_run_id UUID NOT NULL, source_file_name TEXT NOT NULL,
    source_row_number INTEGER NOT NULL CHECK (source_row_number > 0),
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sku TEXT, product_name TEXT, brand TEXT, category TEXT, price TEXT, source_payload JSONB NOT NULL,
    CONSTRAINT uq_raw_product_master_file_row UNIQUE (ingestion_run_id, source_file_name, source_row_number)
);

-- Compatibility migration for databases initialized by the earlier source contract.
-- Raw data remains source-faithful (including Shopee customer_id in source_payload),
-- while downstream clean tables deliberately exclude that source-only attribute.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'shopee_orders' AND column_name = 'order_status'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'shopee_orders' AND column_name = 'status'
    ) THEN
        ALTER TABLE raw.shopee_orders RENAME COLUMN order_status TO status;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'tokopedia_transactions' AND column_name = 'trans_date'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'tokopedia_transactions' AND column_name = 'transaction_date'
    ) THEN
        ALTER TABLE raw.tokopedia_transactions RENAME COLUMN trans_date TO transaction_date;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'tokopedia_transactions' AND column_name = 'amount'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'tokopedia_transactions' AND column_name = 'price'
    ) THEN
        ALTER TABLE raw.tokopedia_transactions RENAME COLUMN amount TO price;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'offline_store_sales' AND column_name = 'sale_status'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'raw' AND table_name = 'offline_store_sales' AND column_name = 'status'
    ) THEN
        ALTER TABLE raw.offline_store_sales RENAME COLUMN sale_status TO status;
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_raw_shopee_order_id ON raw.shopee_orders (order_id);
CREATE INDEX IF NOT EXISTS idx_raw_tokopedia_transaction_id ON raw.tokopedia_transactions (transaction_id);
CREATE INDEX IF NOT EXISTS idx_raw_website_invoice_no ON raw.website_transactions (invoice_no);
CREATE INDEX IF NOT EXISTS idx_raw_offline_receipt_no ON raw.offline_store_sales (pos_receipt_no);
CREATE INDEX IF NOT EXISTS idx_raw_product_master_sku ON raw.product_master (sku);
