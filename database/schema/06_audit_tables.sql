CREATE TABLE IF NOT EXISTS audit.pipeline_runs (
    run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pipeline_name VARCHAR(100) NOT NULL,
    started_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ended_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL CHECK (status IN ('RUNNING', 'SUCCESS', 'FAILED', 'PARTIAL_SUCCESS')),
    extracted_records INTEGER NOT NULL DEFAULT 0 CHECK (extracted_records >= 0),
    valid_records INTEGER NOT NULL DEFAULT 0 CHECK (valid_records >= 0),
    duplicate_records INTEGER NOT NULL DEFAULT 0 CHECK (duplicate_records >= 0),
    invalid_records INTEGER NOT NULL DEFAULT 0 CHECK (invalid_records >= 0),
    loaded_records INTEGER NOT NULL DEFAULT 0 CHECK (loaded_records >= 0),
    error_message TEXT,
    CONSTRAINT chk_pipeline_run_end CHECK (ended_at IS NULL OR ended_at >= started_at)
);

CREATE TABLE IF NOT EXISTS audit.data_quality_results (
    quality_result_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id) ON DELETE CASCADE,
    source_name VARCHAR(30) NOT NULL,
    rule_name VARCHAR(100) NOT NULL,
    severity VARCHAR(10) NOT NULL CHECK (severity IN ('INFO', 'WARNING', 'ERROR')),
    failed_records INTEGER NOT NULL CHECK (failed_records >= 0),
    evaluated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    details JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS audit.rejected_records (
    rejected_record_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id) ON DELETE CASCADE,
    source_name VARCHAR(30) NOT NULL,
    source_order_id TEXT,
    source_row_number INTEGER,
    rejection_reason TEXT NOT NULL,
    source_payload JSONB NOT NULL,
    rejected_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit.pipeline_watermarks (
    pipeline_name VARCHAR(100) NOT NULL,
    source_name VARCHAR(30) NOT NULL,
    last_successful_run_id UUID REFERENCES audit.pipeline_runs(run_id),
    last_processed_at TIMESTAMPTZ,
    last_business_key TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (pipeline_name, source_name)
);

CREATE TABLE IF NOT EXISTS audit.source_ingestions (
    source_ingestion_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES audit.pipeline_runs(run_id) ON DELETE CASCADE,
    source_name VARCHAR(30) NOT NULL,
    source_file_name TEXT NOT NULL,
    source_file_path TEXT NOT NULL,
    file_checksum_sha256 CHAR(64) NOT NULL,
    source_format VARCHAR(10) NOT NULL CHECK (source_format IN ('CSV', 'JSON')),
    extracted_records INTEGER NOT NULL CHECK (extracted_records >= 0),
    extracted_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_source_ingestion_file UNIQUE (run_id, source_name, file_checksum_sha256)
);

CREATE INDEX IF NOT EXISTS idx_audit_runs_pipeline_started ON audit.pipeline_runs (pipeline_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_audit_quality_run ON audit.data_quality_results (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_rejected_run ON audit.rejected_records (run_id);
CREATE INDEX IF NOT EXISTS idx_audit_source_ingestions_run ON audit.source_ingestions (run_id);

-- Raw and staging run IDs reference the audit table only after it exists.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_raw_shopee_run') THEN
        ALTER TABLE raw.shopee_orders ADD CONSTRAINT fk_raw_shopee_run FOREIGN KEY (ingestion_run_id) REFERENCES audit.pipeline_runs(run_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_raw_tokopedia_run') THEN
        ALTER TABLE raw.tokopedia_transactions ADD CONSTRAINT fk_raw_tokopedia_run FOREIGN KEY (ingestion_run_id) REFERENCES audit.pipeline_runs(run_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_raw_website_run') THEN
        ALTER TABLE raw.website_transactions ADD CONSTRAINT fk_raw_website_run FOREIGN KEY (ingestion_run_id) REFERENCES audit.pipeline_runs(run_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_raw_offline_run') THEN
        ALTER TABLE raw.offline_store_sales ADD CONSTRAINT fk_raw_offline_run FOREIGN KEY (ingestion_run_id) REFERENCES audit.pipeline_runs(run_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_raw_product_run') THEN
        ALTER TABLE raw.product_master ADD CONSTRAINT fk_raw_product_run FOREIGN KEY (ingestion_run_id) REFERENCES audit.pipeline_runs(run_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_stg_sales_run') THEN
        ALTER TABLE staging.stg_sales ADD CONSTRAINT fk_stg_sales_run FOREIGN KEY (ingestion_run_id) REFERENCES audit.pipeline_runs(run_id);
    END IF;
END $$;
