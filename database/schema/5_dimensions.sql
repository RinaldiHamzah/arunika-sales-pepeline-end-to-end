CREATE TABLE IF NOT EXISTS warehouse.dim_date (
    date_key INTEGER PRIMARY KEY CHECK (date_key BETWEEN 20000101 AND 21001231),
    full_date DATE NOT NULL UNIQUE,
    day_of_month SMALLINT NOT NULL CHECK (day_of_month BETWEEN 1 AND 31),
    month_number SMALLINT NOT NULL CHECK (month_number BETWEEN 1 AND 12),
    month_name VARCHAR(12) NOT NULL,
    quarter_number SMALLINT NOT NULL CHECK (quarter_number BETWEEN 1 AND 4),
    year_number SMALLINT NOT NULL CHECK (year_number BETWEEN 2000 AND 2100),
    day_name VARCHAR(12) NOT NULL,
    is_weekend BOOLEAN NOT NULL
);

CREATE TABLE IF NOT EXISTS warehouse.dim_product (
    product_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku VARCHAR(30) NOT NULL UNIQUE,
    product_name TEXT NOT NULL,
    brand VARCHAR(80) NOT NULL,
    category VARCHAR(80) NOT NULL,
    standard_price NUMERIC(14,2) NOT NULL CHECK (standard_price >= 0),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS warehouse.dim_customer (
    customer_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    customer_nk TEXT NOT NULL UNIQUE,
    customer_name TEXT,
    city VARCHAR(100),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS warehouse.dim_channel (
    channel_key SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    channel_code VARCHAR(30) NOT NULL UNIQUE CHECK (channel_code IN ('SHOPEE', 'TOKOPEDIA', 'WEBSITE', 'OFFLINE_STORE')),
    channel_name VARCHAR(80) NOT NULL UNIQUE,
    channel_type VARCHAR(30) NOT NULL CHECK (channel_type IN ('MARKETPLACE', 'DIRECT', 'OFFLINE'))
);

CREATE TABLE IF NOT EXISTS warehouse.dim_payment (
    payment_key SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    payment_method VARCHAR(60) NOT NULL UNIQUE
);

-- Static channel members; the ETL only needs to resolve these keys.
INSERT INTO warehouse.dim_channel (channel_code, channel_name, channel_type)
VALUES
    ('SHOPEE', 'Shopee', 'MARKETPLACE'),
    ('TOKOPEDIA', 'Tokopedia', 'MARKETPLACE'),
    ('WEBSITE', 'Arunika Beauty Website', 'DIRECT'),
    ('OFFLINE_STORE', 'Arunika Beauty Store', 'OFFLINE')
ON CONFLICT (channel_code) DO UPDATE
SET channel_name = EXCLUDED.channel_name,
    channel_type = EXCLUDED.channel_type;

CREATE INDEX IF NOT EXISTS idx_dim_product_brand_category ON warehouse.dim_product (brand, category);
CREATE INDEX IF NOT EXISTS idx_dim_customer_city ON warehouse.dim_customer (city);
