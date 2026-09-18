# Data Dictionary

## Warehouse tables

### `warehouse.fact_sales`

Grain: one product line in one source order. Primary key: `sales_key`. Natural
business key: `(source_name, source_order_id, source_line_number)`.

| Column | Type | Meaning |
| --- | --- | --- |
| `sales_key` | BIGINT | Warehouse surrogate key |
| `source_name` | VARCHAR | `SHOPEE`, `TOKOPEDIA`, `WEBSITE`, or `OFFLINE_STORE` |
| `source_order_id` | TEXT | Identifier from the source |
| `source_line_number` | INTEGER | Line within the order; currently `1` |
| `date_key` | INTEGER | FK to `dim_date` |
| `product_key` | BIGINT | FK to `dim_product` |
| `customer_key` | BIGINT | Nullable FK to `dim_customer` |
| `channel_key` | SMALLINT | FK to `dim_channel` |
| `payment_key` | SMALLINT | Nullable FK to `dim_payment` |
| `sale_status` | VARCHAR | `COMPLETED`, `CANCELLED`, or `RETURNED` |
| `quantity` | INTEGER | Positive units sold |
| `unit_price` | NUMERIC(14,2) | Transaction unit price |
| `gross_amount` | NUMERIC(16,2) | Quantity multiplied by unit price |
| `discount_amount` | NUMERIC(16,2) | Current default is zero |
| `net_amount` | NUMERIC(16,2) | Gross amount less discount |
| `source_record_hash` | CHAR(64) | Content hash for correction detection and idempotent upsert |
| `is_source_active` | BOOLEAN | Source snapshot activity flag; rows are not hard-deleted |

### Dimensions

| Table | Key | Purpose |
| --- | --- | --- |
| `warehouse.dim_product` | `product_key`, unique `sku` | Master SKU, product name, brand, category, standard price |
| `warehouse.dim_date` | `date_key` | Calendar attributes for daily/monthly analysis |
| `warehouse.dim_customer` | `customer_key`, unique `customer_nk` | Source-scoped customer identity and city |
| `warehouse.dim_channel` | `channel_key`, unique `channel_code` | Channel name and channel type |
| `warehouse.dim_payment` | `payment_key`, unique `payment_method` | Canonical payment method |

### Staging and audit

| Table | Purpose |
| --- | --- |
| `staging.stg_sales` | Validated canonical rows with raw record lineage before FK resolution |
| `audit.pipeline_runs` | Run status, duration, and extracted/validated/incremental/staging/dimension/fact counts |
| `audit.data_quality_results` | Rule/severity aggregates per run |
| `audit.rejected_records` | Rejected source payloads and reasons |
| `audit.pipeline_watermarks` | Last successful source/run marker |
| `audit.source_ingestions` | File checksum, path, format, and extracted count |
