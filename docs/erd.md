# ERD Warehouse dan Audit

Diagram berikut merangkum tabel dan relasi utama. `PK` menandai primary key, `FK` menandai foreign key, dan `UNQ` menandai unique key.

## Star Schema Warehouse

![Arsitektur star schema Data Warehouse](images/warehouse-star-schema.png)



## ERD Lengkap

![ERD lengkap Raw, Staging, Audit, dan Warehouse](images/erd-full.png)

Diagram lengkap mencakup relasi `audit.pipeline_runs` dengan Raw, Staging, dan tabel audit operasional, serta relasi `warehouse.fact_sales` dengan seluruh tabel dimensi.

File sumber diagram yang dapat diedit menggunakan Draw.io tersedia pada `diagrams/erd_full.drawio`.

## Analytics Views

View berikut adalah objek baca saja. View tidak ditampilkan sebagai tabel pada ERD karena tidak menyimpan data sendiri; semuanya dibentuk dari tabel Warehouse dan Audit.

| View | Sumber data utama | Kegunaan |
| --- | --- | --- |
| `warehouse.v_sales_detail` | `fact_sales` dan seluruh dimensi terkait | Dataset transaksi canonical untuk dashboard, filter, tabel rincian transaksi, dan ekspor CSV. |
| `warehouse.v_sales_by_month` | `fact_sales`, `dim_date` | Agregasi penjualan, unit, dan nilai gross/net per bulan serta status. |
| `warehouse.v_sales_by_channel` | `fact_sales`, `dim_channel` | Agregasi penjualan per kanal dan status. |
| `warehouse.v_sales_by_product` | `fact_sales`, `dim_product` | Agregasi penjualan per produk, brand, kategori, dan status. |
| `warehouse.v_sales_kpi` | `fact_sales` | KPI keseluruhan: gross sales, net sales, completed order, returned order, unit terjual, return rate, dan AOV. |
| `warehouse.v_sales_monthly_kpi` | `fact_sales`, `dim_date` | KPI utama yang dikelompokkan per bulan. |
| `warehouse.v_sales_channel_kpi` | `fact_sales`, `dim_channel` | KPI utama yang dikelompokkan per kanal penjualan. |
| `warehouse.v_top_product_kpi` | `fact_sales`, `dim_product` | Dasar analisis produk teratas berdasarkan penjualan dan unit order COMPLETED. |
| `warehouse.v_sales_status_kpi` | `fact_sales` | Jumlah order, unit, gross sales, dan net sales per status transaksi. |
| `warehouse.v_pipeline_quality` | `audit.pipeline_runs`, `audit.data_quality_results` | Ringkasan kualitas dan metrik setiap eksekusi pipeline. |
| `audit.v_data_quality_by_rule` | `audit.pipeline_runs`, `audit.data_quality_results` | Bukti quality check per run, source, dan aturan validasi. |
| `audit.v_data_quality_report` | `audit.pipeline_runs`, `audit.data_quality_results` | Laporan kualitas per run dan source: missing value, duplicate, invalid value, invalid date, status, serta product mapping. |

## Grain tabel

| Tabel | Grain / satu baris merepresentasikan |
| --- | --- |
| `raw.shopee_orders` | Satu baris mentah CSV Shopee dalam satu ingestion run. |
| `raw.tokopedia_transactions` | Satu baris mentah CSV Tokopedia dalam satu ingestion run. |
| `raw.website_transactions` | Satu baris mentah CSV Website dalam satu ingestion run. |
| `raw.offline_store_sales` | Satu baris mentah CSV toko offline dalam satu ingestion run. |
| `raw.product_master` | Satu baris master produk dalam satu ingestion run. |
| `staging.stg_sales` | Satu line item transaksi canonical yang valid. |
| `warehouse.fact_sales` | Satu produk dalam satu transaksi source. Business key: `(source_name, source_order_id, source_line_number)`. |
| `warehouse.dim_date` | Satu tanggal kalender. |
| `warehouse.dim_product` | Satu SKU produk canonical. |
| `warehouse.dim_customer` | Satu customer natural key per source. |
| `warehouse.dim_channel` | Satu channel penjualan. |
| `warehouse.dim_payment` | Satu metode pembayaran canonical. |
| `audit.pipeline_runs` | Satu eksekusi pipeline. |
| `audit.source_ingestions` | Satu file source yang diekstrak dalam satu run. |
| `audit.pipeline_stage_runs` | Satu tahap pemrosesan dalam satu run. |
| `audit.pipeline_watermarks` | Satu watermark per pipeline dan source; menyimpan run sukses terakhir, waktu proses, dan penanda pemrosesan source. |
| `audit.data_quality_results` | Satu rule kualitas per source per run. |
| `audit.rejected_records` | Satu baris transaksi yang ditolak dalam satu run. |
| `audit.source_snapshots` | Snapshot terakhir satu source untuk incremental loading. |

Pada staging, `source_raw_record_id` menghubungkan baris bersih dengan data raw yang menjadi asalnya. Hubungan ini dijaga oleh pipeline. Database menerapkan foreign key untuk `ingestion_run_id` dan seluruh relasi fact ke dimensi.
