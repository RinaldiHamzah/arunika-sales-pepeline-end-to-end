-- Source schema for raw files supplied by Arunika Beauty.
-- Safe to rerun: PostgreSQL will keep the existing schema when it already exists.
CREATE SCHEMA IF NOT EXISTS arunika_source;

COMMENT ON SCHEMA arunika_source IS
    'Source-layer data for Arunika Beauty: Shopee, Tokopedia, Website, Offline Store, and Product Master.';

-- ============================================================================
-- STAR SCHEMA: ARUNIKA BEAUTY SALES
-- Grain fact_sales: one product line in one order from one sales channel.
-- Source files represented: product.csv, shopee.csv, tokopedia.csv,
-- website.csv, and offline.csv.
-- ============================================================================

-- Product Master: product.csv
CREATE TABLE IF NOT EXISTS arunika_source.dim_product (
    product_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    product_id VARCHAR(30) NOT NULL UNIQUE,
    product_name VARCHAR(255) NOT NULL,
    brand VARCHAR(100) NOT NULL,
    kategori VARCHAR(100) NOT NULL,
    harga_satuan NUMERIC(14, 2) NOT NULL CHECK (harga_satuan > 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Calendar dimension derived from tanggal_order.
CREATE TABLE IF NOT EXISTS arunika_source.dim_date (
    date_key INTEGER PRIMARY KEY CHECK (date_key BETWEEN 20000101 AND 21001231),
    tanggal_order DATE NOT NULL UNIQUE,
    hari SMALLINT NOT NULL CHECK (hari BETWEEN 1 AND 31),
    nama_hari VARCHAR(12) NOT NULL,
    bulan SMALLINT NOT NULL CHECK (bulan BETWEEN 1 AND 12),
    nama_bulan VARCHAR(12) NOT NULL,
    kuartal SMALLINT NOT NULL CHECK (kuartal BETWEEN 1 AND 4),
    tahun SMALLINT NOT NULL CHECK (tahun BETWEEN 2000 AND 2100),
    is_weekend BOOLEAN NOT NULL
);

-- Sales channel dimension: Shopee, Tokopedia, Website, Offline Store.
CREATE TABLE IF NOT EXISTS arunika_source.dim_channel (
    channel_key SMALLINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    channel_name VARCHAR(50) NOT NULL UNIQUE,
    channel_type VARCHAR(30) NOT NULL CHECK (
        channel_type IN ('MARKETPLACE', 'WEBSITE', 'OFFLINE_STORE')
    )
);

INSERT INTO arunika_source.dim_channel (channel_name, channel_type)
VALUES
    ('Shopee', 'MARKETPLACE'),
    ('Tokopedia', 'MARKETPLACE'),
    ('Website', 'WEBSITE'),
    ('Offline Store', 'OFFLINE_STORE')
ON CONFLICT (channel_name) DO UPDATE
SET channel_type = EXCLUDED.channel_type;

-- Fact table built from the four standardized clean source files.
-- customer_id is intentionally excluded because it is not available in every source.
CREATE TABLE IF NOT EXISTS arunika_source.fact_sales (
    sales_key BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    order_id VARCHAR(50) NOT NULL,
    line_number SMALLINT NOT NULL DEFAULT 1 CHECK (line_number > 0),
    product_key BIGINT NOT NULL REFERENCES arunika_source.dim_product(product_key),
    date_key INTEGER NOT NULL REFERENCES arunika_source.dim_date(date_key),
    channel_key SMALLINT NOT NULL REFERENCES arunika_source.dim_channel(channel_key),
    kota VARCHAR(100),
    status VARCHAR(20) NOT NULL CHECK (status IN ('Completed', 'Cancelled', 'Returned')),
    customer_email VARCHAR(255),
    quantity INTEGER NOT NULL CHECK (quantity > 0),
    harga_satuan NUMERIC(14, 2) NOT NULL CHECK (harga_satuan > 0),
    total_harga NUMERIC(16, 2) NOT NULL CHECK (total_harga > 0),
    loaded_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_fact_sales_business_key UNIQUE (channel_key, order_id, line_number),
    CONSTRAINT chk_fact_sales_total_harga CHECK (total_harga = quantity * harga_satuan)
);

-- Indexes for joins and common analytical filters.
CREATE INDEX IF NOT EXISTS idx_fact_sales_product_key
    ON arunika_source.fact_sales (product_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_date_key
    ON arunika_source.fact_sales (date_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_channel_date
    ON arunika_source.fact_sales (channel_key, date_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_status_date
    ON arunika_source.fact_sales (status, date_key);
CREATE INDEX IF NOT EXISTS idx_fact_sales_kota
    ON arunika_source.fact_sales (kota);
CREATE INDEX IF NOT EXISTS idx_dim_product_brand_kategori
    ON arunika_source.dim_product (brand, kategori);

COMMENT ON TABLE arunika_source.dim_product IS
    'Dimension product loaded from data/source/product.csv.';
COMMENT ON TABLE arunika_source.dim_date IS
    'Dimension calendar generated from clean transaction tanggal_order.';
COMMENT ON TABLE arunika_source.dim_channel IS
    'Sales channel lookup for Shopee, Tokopedia, Website, and Offline Store.';
COMMENT ON TABLE arunika_source.fact_sales IS
    'Fact sales loaded from clean source files. One row represents one product in one order.';
