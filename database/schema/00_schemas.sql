-- Canonical database namespaces. Loaded before all table definitions.
CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS staging;
CREATE SCHEMA IF NOT EXISTS warehouse;
CREATE SCHEMA IF NOT EXISTS audit;

COMMENT ON SCHEMA raw IS 'Source-faithful records and ingestion metadata.';
COMMENT ON SCHEMA staging IS 'Validated canonical rows before warehouse key resolution.';
COMMENT ON SCHEMA warehouse IS 'Analytics star schema.';
COMMENT ON SCHEMA audit IS 'Pipeline runs, quality evidence, and source lineage.';
