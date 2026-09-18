# Arunika Sales — Technical Documentation & Runbook

## Architecture and lineage

CSV marketplace (Shopee/Tokopedia), website, offline, and product master → `pipeline.extract` → `raw` PostgreSQL → validation/DQ → `staging.stg_sales` → `warehouse` star schema → `warehouse.v_sales_detail` → Flask dashboard and SQL analytics. Audit tables record every run, stage, checksum, freshness, and rejection metric.

## Source-to-target mapping

Extractors harmonize each source into the canonical sales contract: `source_name`, `order_id`, `order_date`, `product_id`, `product_name`, `category`, `brand`, `quantity`, `unit_price`, `gross_amount`, `net_amount`, `status`, `city`, and `payment_method`. Product IDs are resolved against `warehouse.dim_product`; unknown products are rejected and written to the rejected output.

## Warehouse grain and keys

`warehouse.fact_sales` grain is one product line per transaction. The natural business key is `(source_name, order_id, line_number)`; `sales_key` is the surrogate primary key. Dimensions use surrogate keys and unique natural keys (SKU, customer, channel, payment, date).

## Data quality treatment

Required identifiers and dates are rejected when empty; quantity and prices must be non-negative; status is restricted to the canonical status set; dates are parsed to ISO `YYYY-MM-DD`; numeric fields are stored as numeric types; duplicate business keys are skipped and counted. Every rejected row includes a rule and reason.

## Incremental strategy

The pipeline computes a source hash per business key. New keys are inserted, changed hashes are updated, and identical hashes are skipped. Rows missing from a later snapshot are retained as active history (no destructive delete). Late-arriving rows are accepted using their event date while ingestion time remains auditable.

## Failure recovery and migration

Inspect `audit.pipeline_runs` and `audit.pipeline_stage_runs`, fix the source or dependency, then rerun safely (idempotent). Failed runs are never treated as successful. Apply schema changes with `alembic upgrade head`; do not rely on recreating the PostgreSQL volume.

## Operations

Start with `docker compose up -d`, run the pipeline service or Airflow DAG, and verify `GET /healthz`, `scripts/check_warehouse.py`, and `scripts/check_freshness.py`. Dashboard API is available at `/api/dashboard`; filtered records can be exported from `/api/dashboard/export`.

## Dashboard and API

The dashboard provides date/channel/status/category/brand/product filters, Today/7D/30D/YTD presets, net and gross sales, period comparison, top SKU/brand, pagination, CSV export, freshness, and DQ warnings. API responses contain `metrics`, `charts`, `rows`, `options`, and `observability` (pipeline success rate, duration, rejection/duplicate/load rates, and stage timing).

## Known limitations

The sample sources are synthetic; discount and return semantics depend on source status; PostgreSQL is the reference warehouse; alert delivery is optional and configured through environment variables. Production deployments should use managed secrets, a least-privilege database role, TLS, and an external metrics/alerting backend.
