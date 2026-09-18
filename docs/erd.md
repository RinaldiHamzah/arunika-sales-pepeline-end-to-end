# Entity Relationship Diagram

```mermaid
erDiagram
	DIM_DATE ||--o{ FACT_SALES : dates
	DIM_PRODUCT ||--o{ FACT_SALES : products
	DIM_CUSTOMER ||--o{ FACT_SALES : customers
	DIM_CHANNEL ||--o{ FACT_SALES : channels
	DIM_PAYMENT ||--o{ FACT_SALES : payments
	PIPELINE_RUNS ||--o{ STG_SALES : stages
	PIPELINE_RUNS ||--o{ SOURCE_INGESTIONS : ingests
	PIPELINE_RUNS ||--o{ DATA_QUALITY_RESULTS : measures
	PIPELINE_RUNS ||--o{ REJECTED_RECORDS : rejects
	PIPELINE_RUNS ||--o{ FACT_SALES : loads

	DIM_DATE { int date_key PK }
	DIM_PRODUCT { bigint product_key PK string sku UK }
	DIM_CUSTOMER { bigint customer_key PK string customer_nk UK }
	DIM_CHANNEL { smallint channel_key PK string channel_code UK }
	DIM_PAYMENT { smallint payment_key PK string payment_method UK }
	FACT_SALES { bigint sales_key PK string source_name string source_order_id int source_line_number }
	STG_SALES { bigint staging_sales_id PK uuid ingestion_run_id FK string mapped_sku }
	PIPELINE_RUNS { uuid run_id PK string status int extracted_records int loaded_records }
```

The fact grain is one source order line. Since current sources provide one item
per order, `source_line_number` is always `1`; it is retained so the model can
support multi-line orders when a stable source line identifier becomes available.
Surrogate dimension keys keep joins compact and stable, while source order keys
remain on the fact for auditability and incremental duplicate prevention.
