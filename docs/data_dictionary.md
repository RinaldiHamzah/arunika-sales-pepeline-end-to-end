# Kamus Data

Dokumen ini menjelaskan kolom dan fungsi tabel operasional utama. `PK` berarti primary key, `FK` berarti foreign key, dan `UK` berarti unique key. Relasi antartabel ditampilkan pada [ERD](erd.md).

## Raw layer

Setiap tabel raw menyimpan **satu baris sumber dalam satu ingestion run**. Kolom lineage yang digunakan adalah:

| Field | Tipe | Key | Fungsi |
| --- | --- | --- | --- |
| `raw_record_id` | BIGINT | PK | Identitas teknis raw record. |
| `ingestion_run_id` | UUID | FK → `audit.pipeline_runs.run_id` | Run yang menyimpan payload. |
| `source_file_name` | TEXT |  | Nama file asal. |
| `source_row_number` | INTEGER | UK bersama run/file | Nomor baris CSV asal. |
| `ingested_at` | TIMESTAMPTZ |  | Waktu landing ke raw. |
| `source_payload` | JSONB |  | Payload source utuh tanpa transformasi. |

Kolom khusus sumber tetap disimpan sebagai `TEXT`. Dengan begitu, nilai yang tidak valid tetap tersimpan dan dapat diperiksa.

| Tabel | Field source-specific utama | Fungsi |
| --- | --- | --- |
| `raw.shopee_orders` | `order_id`, `order_date`, `product_name`, `qty`, `unit_price`, `customer_name`, `customer_city`, `payment_method`, `status` | Payload marketplace Shopee. |
| `raw.tokopedia_transactions` | `transaction_id`, `transaction_date`, `item_name`, `quantity`, `price`, `buyer_name`, `city`, `payment`, `status` | Payload marketplace Tokopedia. |
| `raw.website_transactions` | `invoice_no`, `created_at`, `product_identifier`, `quantity`, `unit_price`, `total_amount`, `customer_email`, `status` | Payload transaksi website. |
| `raw.offline_store_sales` | `pos_receipt_no`, `sold_at`, `item_description`, `units`, `item_price`, `store_name`, `store_city`, `payment_type`, `status` | Payload POS toko offline. |
| `raw.product_master` | `sku`, `product_name`, `brand`, `category`, `price` | Referensi master produk. |

## Staging

`staging.stg_sales` memiliki grain **satu line item transaksi valid**.

| Field | Tipe | Key | Fungsi |
| --- | --- | --- | --- |
| `staging_sales_id` | BIGINT | PK | Identitas staging. |
| `ingestion_run_id` | UUID | FK → pipeline run | Run transformasi. |
| `source_name` | VARCHAR(30) | UK gabungan | Channel canonical source. |
| `source_raw_record_id` | BIGINT |  | Identitas raw record untuk lineage. |
| `source_order_id` | TEXT | UK gabungan | Order ID source. |
| `source_line_number` | INTEGER | UK gabungan | Line item source; saat ini umumnya `1`. |
| `order_date` | DATE |  | Tanggal transaksi canonical. |
| `product_input` | TEXT |  | Nama/SKU produk sebelum mapping. |
| `mapped_sku` | VARCHAR(30) |  | SKU Product Master hasil mapping. |
| `customer_nk` | TEXT |  | Natural key customer canonical. |
| `customer_name`, `city` | TEXT |  | Atribut customer terstandar. |
| `payment_method`, `sale_status` | VARCHAR |  | Pembayaran dan status canonical. |
| `quantity` | INTEGER |  | Unit positif tervalidasi. |
| `unit_price`, `gross_amount`, `source_total_amount` | NUMERIC |  | Nilai transaksi canonical. |
| `source_record_hash` | CHAR(64) |  | Hash untuk deteksi koreksi. |
| `is_valid`, `validation_notes` | BOOLEAN, JSONB |  | Bukti hasil validasi. |

## Warehouse dimensions

| Tabel / field | Tipe | Key | Fungsi |
| --- | --- | --- | --- |
| `dim_date.date_key` | INTEGER | PK | Kunci tanggal format `YYYYMMDD`. |
| `dim_date.full_date` | DATE | UK | Tanggal kalender. |
| `dim_date.day_of_month`, `month_number`, `month_name`, `quarter_number`, `year_number`, `day_name`, `is_weekend` | SMALLINT/VARCHAR/BOOLEAN |  | Atribut waktu untuk analitik. |
| `dim_product.product_key` | BIGINT | PK | Surrogate key produk. |
| `dim_product.sku` | VARCHAR(30) | UK | Product ID/master SKU. |
| `dim_product.product_name`, `brand`, `category` | TEXT/VARCHAR |  | Atribut produk. |
| `dim_product.standard_price`, `is_active` | NUMERIC/BOOLEAN |  | Harga referensi dan status produk. |
| `dim_customer.customer_key` | BIGINT | PK | Surrogate key customer. |
| `dim_customer.customer_nk` | TEXT | UK | Natural key customer per source. |
| `dim_customer.customer_name`, `city` | TEXT/VARCHAR |  | Atribut customer terverifikasi. |
| `dim_channel.channel_key` | SMALLINT | PK | Surrogate key channel. |
| `dim_channel.channel_code` | VARCHAR(30) | UK | `SHOPEE`, `TOKOPEDIA`, `WEBSITE`, atau `OFFLINE_STORE`. |
| `dim_channel.channel_name`, `channel_type` | VARCHAR |  | Nama dan jenis channel. |
| `dim_payment.payment_key` | SMALLINT | PK | Surrogate key pembayaran. |
| `dim_payment.payment_method` | VARCHAR(60) | UK | Metode pembayaran canonical. |

## Fact sales

`warehouse.fact_sales` memiliki grain **satu produk dalam satu transaksi source**.

| Field | Tipe | Key | Fungsi |
| --- | --- | --- | --- |
| `sales_key` | BIGINT | PK | Surrogate key fact. |
| `source_name`, `source_order_id`, `source_line_number` | VARCHAR/TEXT/INTEGER | UK gabungan | Business key transaksi. |
| `date_key` | INTEGER | FK → `dim_date` | Tanggal transaksi. |
| `product_key` | BIGINT | FK → `dim_product` | Produk yang terjual. |
| `customer_key` | BIGINT | FK → `dim_customer`, nullable | Customer jika tersedia. |
| `channel_key` | SMALLINT | FK → `dim_channel` | Channel penjualan. |
| `payment_key` | SMALLINT | FK → `dim_payment`, nullable | Metode pembayaran. |
| `sale_status` | VARCHAR(20) |  | `COMPLETED`, `CANCELLED`, atau `RETURNED`. |
| `quantity`, `unit_price` | INTEGER, NUMERIC(14,2) |  | Unit dan harga source tervalidasi. |
| `gross_amount` | NUMERIC(16,2) |  | `quantity × unit_price`. |
| `discount_amount` | NUMERIC(16,2) |  | Diskon; saat ini source belum menyediakan diskon sehingga bernilai nol. |
| `net_amount` | NUMERIC(16,2) |  | `gross_amount - discount_amount`. |
| `source_record_hash` | CHAR(64) |  | Deteksi koreksi dan idempotensi. |
| `is_source_active`, `loaded_at` | BOOLEAN, TIMESTAMPTZ |  | Status source dan waktu warehouse load. |

## Audit dan observability

| Tabel | Grain | Field kunci | Fungsi |
| --- | --- | --- | --- |
| `audit.pipeline_runs` | Satu pipeline run | `run_id` PK; status, waktu, metrik record | Audit run utama. |
| `audit.pipeline_stage_runs` | Satu stage pada satu run | `stage_run_id` PK; `run_id` FK | Durasi dan error tiap tahap. |
| `audit.source_ingestions` | Satu source file pada satu run | `source_ingestion_id` PK; `run_id` FK | Checksum, path, format, jumlah record. |
| `audit.source_snapshots` | Snapshot terbaru per pipeline/source | `(pipeline_name, source_name)` PK | Payload hash untuk incremental. |
| `audit.data_quality_results` | Satu rule/source/run | `quality_result_id` PK; `run_id` FK | Jumlah kegagalan per rule dan severity. |
| `audit.rejected_records` | Satu baris transaksi yang ditolak dalam satu run | `rejected_record_id` PK; `run_id` FK | Payload asli dan alasan penolakan. |
| `audit.pipeline_watermarks` | Watermark per pipeline/source | `(pipeline_name, source_name)` PK | Run sukses dan waktu proses terakhir. |

Kolom `audit.pipeline_runs.report_summary` bertipe `JSONB`. Nilainya dapat `NULL` pada run lama. Pada run baru, kolom ini menyimpan ringkasan untuk run tersebut: bagian `raw`, `quality_staging`, dan `warehouse`. Dashboard dan email membaca ringkasan yang sama agar angka laporan konsisten.

View pelaporan tersedia pada `warehouse.v_sales_kpi`, `warehouse.v_sales_monthly_kpi`, `warehouse.v_sales_channel_kpi`, `warehouse.v_top_product_kpi`, `warehouse.v_sales_status_kpi`, `audit.v_data_quality_by_rule`, dan `audit.v_data_quality_report`. View terakhir merangkum total source, kandidat baru, data identik yang dilewati, valid, rejected, duplicate, serta kategori missing, quantity, price/amount, date, status, produk, dan warning per source.
