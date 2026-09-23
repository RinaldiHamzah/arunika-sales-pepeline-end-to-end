# Diagram Relasi Entitas

```mermaid
erDiagram
    DIM_DATE ||--o{ FACT_SALES : tanggal
    DIM_PRODUCT ||--o{ FACT_SALES : produk
    DIM_CUSTOMER ||--o{ FACT_SALES : pelanggan
    DIM_CHANNEL ||--o{ FACT_SALES : channel
    DIM_PAYMENT ||--o{ FACT_SALES : pembayaran
    PIPELINE_RUNS ||--o{ STG_SALES : memuat
    PIPELINE_RUNS ||--o{ SOURCE_INGESTIONS : mengingest
    PIPELINE_RUNS ||--o{ DATA_QUALITY_RESULTS : mengukur
    PIPELINE_RUNS ||--o{ REJECTED_RECORDS : menolak
    PIPELINE_RUNS ||--o{ FACT_SALES : memuat_fact

    DIM_DATE { int date_key PK }
    DIM_PRODUCT { bigint product_key PK string sku UK }
    DIM_CUSTOMER { bigint customer_key PK string customer_nk UK }
    DIM_CHANNEL { smallint channel_key PK string channel_code UK }
    DIM_PAYMENT { smallint payment_key PK string payment_method UK }
    FACT_SALES { bigint sales_key PK string source_name string source_order_id int source_line_number }
    STG_SALES { bigint staging_sales_id PK uuid ingestion_run_id FK string mapped_sku }
    PIPELINE_RUNS { uuid run_id PK string status int extracted_records int loaded_records }
```

`FACT_SALES` menyimpan satu produk dalam satu transaksi source. Source saat ini umumnya memiliki satu item per order sehingga `source_line_number` bernilai `1`. Kolom ini dipertahankan agar model siap menerima transaksi multi-item.

Dimensi memakai surrogate key agar join stabil. Identifier source tetap disimpan pada fact untuk audit, lineage, dan incremental loading.
