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
| `raw.shopee_orders` | `order_id`, `order_line_id`, `order_date`, `product_name`, `qty`, `unit_price`, `customer_name`, `customer_city`, `payment_method`, `status`, `discount_amount`, `promo_code` | Payload marketplace Shopee. |
| `raw.tokopedia_transactions` | `transaction_id`, `item_sequence`, `transaction_date`, `item_name`, `quantity`, `price`, `buyer_name`, `city`, `payment`, `status`, `discount_amount`, `promo_code` | Payload marketplace Tokopedia. |
| `raw.website_transactions` | `invoice_no`, `line_item_no`, `created_at`, `product_identifier`, `quantity`, `unit_price`, `total_amount`, `customer_email`, `status`, `discount_amount`, `promo_code` | Payload transaksi website. |
| `raw.offline_store_sales` | `pos_receipt_no`, `receipt_line_no`, `sold_at`, `item_description`, `units`, `item_price`, `store_name`, `store_city`, `payment_type`, `status`, `discount_amount`, `promo_code` | Payload POS toko offline. |
| `raw.product_master` | `sku`, `product_name`, `brand`, `category`, `price` | Referensi master produk. |
| `raw.promo_master` | `promo_code`, `promo_name`, `discount_type`, `discount_value`, `start_date`, `end_date`, `status` | Riwayat payload katalog promo. |
| `raw.order_promotions` | `source_name`, `order_id`, `promo_code`, `discount_amount` | Tabel legacy untuk audit payload dari format lama; pipeline baru menggunakan diskon per baris dari empat CSV kanal. |
| `raw.return_events` | `source_name`, `return_id`, `return_line_number`, `order_id`, `order_line_number`, `return_date`, `return_reason`, `return_status`, `quantity_returned`, `refund_amount`, `refund_status` | Payload retur dari `return_refund.csv`, disimpan apa adanya untuk lineage. |

## Staging

`staging.stg_sales` memiliki grain **satu line item transaksi valid**.

| Field | Tipe | Key | Fungsi |
| --- | --- | --- | --- |
| `staging_sales_id` | BIGINT | PK | Identitas staging. |
| `ingestion_run_id` | UUID | FK → pipeline run | Run transformasi. |
| `source_name` | VARCHAR(30) | UK gabungan | Channel canonical source. |
| `source_raw_record_id` | BIGINT |  | Identitas raw record untuk lineage. |
| `source_order_id` | TEXT | UK gabungan | Order ID source. |
| `source_line_number` | INTEGER | UK gabungan | Nomor item dalam order dari sumber; wajib positif dan tidak memiliki default. |
| `order_date` | DATE |  | Tanggal transaksi canonical. |
| `product_input` | TEXT |  | Nama/SKU produk sebelum mapping. |
| `mapped_sku` | VARCHAR(30) |  | SKU Product Master hasil mapping. |
| `customer_nk` | TEXT |  | Natural key customer canonical. |
| `customer_name`, `city` | TEXT |  | Atribut customer terstandar. |
| `payment_method`, `sale_status` | VARCHAR |  | Pembayaran dan status canonical. |
| `quantity` | INTEGER |  | Unit positif tervalidasi. |
| `unit_price`, `gross_amount`, `discount_amount`, `net_amount`, `source_total_amount` | NUMERIC |  | Nilai transaksi canonical. `net_amount` dihitung dari gross dikurangi diskon. |
| `promo_code` | TEXT, nullable |  | Kode promo yang diberikan sumber untuk baris item. |
| `source_record_hash` | CHAR(64) |  | Hash untuk deteksi koreksi. |
| `is_valid`, `validation_notes` | BOOLEAN, JSONB |  | Bukti hasil validasi. |

`staging.stg_returns` memiliki grain **satu baris item dalam satu event return/refund yang lolos validasi**. Event invalid tetap dapat ditelusuri melalui Raw dan audit, tetapi tidak diteruskan ke Warehouse.

| Field | Tipe | Key | Fungsi |
| --- | --- | --- | --- |
| `staging_return_id` | BIGINT | PK | Identitas teknis staging. |
| `ingestion_run_id` | UUID | FK → pipeline run | Run yang menormalisasi event. |
| `source_name`, `return_id`, `return_line_number` | VARCHAR/TEXT/INTEGER | UK gabungan | Business key event return pada channel. |
| `source_raw_record_id`, `source_row_number` | BIGINT/INTEGER | FK/raw lineage | Referensi payload Raw dan baris CSV asal. |
| `source_order_id`, `source_line_number` | TEXT/INTEGER | Referensi item fact sales | Order item yang menjadi asal pengajuan return. |
| `return_date`, `return_reason`, `return_status` | DATE/TEXT/VARCHAR |  | Atribut return yang sudah dinormalisasi. |
| `quantity_returned`, `refund_amount`, `refund_status` | INTEGER/NUMERIC/VARCHAR |  | Jumlah unit dan status/nilai refund tervalidasi. |
| `source_record_hash` | CHAR(64) |  | Deteksi koreksi dan idempotensi. |
| `is_valid`, `validation_notes` | BOOLEAN, JSONB |  | Hasil validasi; hanya event valid yang disimpan pada tabel ini. |

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
| `dim_promotion.promo_code` | TEXT | PK | Kode promo dan definisi aturan dari master; nilainya tidak digunakan untuk menebak potongan aktual. |
| `dim_promotion.promo_name`, `discount_type`, `discount_value`, `start_date`, `end_date`, `status`, `is_active` | TEXT/NUMERIC/DATE/BOOLEAN |  | Deskripsi, aturan, periode, status, dan kondisi master promo. |

## Fact sales

`warehouse.fact_sales` memiliki grain **satu baris item dalam satu transaksi source**.

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
| `discount_amount` | NUMERIC(16,2) |  | Diskon aktual per baris item dari sumber; nilai legacy/kosong diperlakukan sebagai nol. |
| `net_amount` | NUMERIC(16,2) |  | `gross_amount - discount_amount`. |
| `promo_code` | TEXT, nullable |  | Kode promo yang dilaporkan kanal pada baris item. |
| `source_record_hash` | CHAR(64) |  | Deteksi koreksi dan idempotensi. |

## Fact retur dan refund

`warehouse.fact_returns` memiliki grain **satu item dalam satu kejadian/pengajuan retur**. Satu order dapat memiliki beberapa item retur dan item yang sama dapat memiliki beberapa kejadian. Business key-nya `(source_name, return_id, return_line_number)`.

| Field | Tipe | Key | Fungsi |
| --- | --- | --- | --- |
| `return_key` | BIGINT | PK | Surrogate key kejadian retur. |
| `source_name`, `return_id`, `return_line_number` | VARCHAR/TEXT/INTEGER | UK gabungan | Identitas event retur pada kanal asal. |
| `source_order_id`, `source_line_number` | TEXT/INTEGER | FK gabungan → `fact_sales` | Baris item penjualan yang dikembalikan. |
| `return_date`, `return_reason` | DATE/TEXT |  | Tanggal dan alasan kejadian. |
| `return_status` | VARCHAR(20) |  | `PENDING`, `APPROVED`, `REJECTED`, atau `PROCESSED`. |
| `quantity_returned` | INTEGER |  | Jumlah unit; akumulasi event non-rejected tidak boleh melebihi quantity penjualan. |
| `refund_amount`, `refund_status` | NUMERIC(16,2)/VARCHAR(20) |  | Nilai refund aktual hanya diisi saat `PROCESSED`; totalnya dibatasi net amount baris penjualan. |
| `source_raw_record_id` | BIGINT | FK → `raw.return_events` | Lineage payload mentah. |
| `source_record_hash`, `ingestion_run_id` | CHAR(64)/UUID | FK run | Deteksi koreksi dan run pemroses. |

Header `data/source/return_refund.csv`:

```csv
source_name,return_id,return_line_number,order_id,order_line_number,return_date,return_reason,return_status,quantity_returned,refund_amount,refund_status
```

`source_name` mencegah benturan ID order antarkanal; `order_line_number` menghubungkan event ke item tertentu, bukan hanya ke order. Tanggal wajib berformat `YYYY-MM-DD`. Baris tidak valid, tidak memiliki penjualan pasangan, atau melampaui batas quantity/net amount dicatat ke `audit.rejected_records` dan `audit.data_quality_results`.
| `is_source_active`, `loaded_at` | BOOLEAN, TIMESTAMPTZ |  | Penanda apakah business key masih ada pada snapshot sumber penuh dan waktu warehouse load. Baris tidak aktif tetap disimpan untuk audit. |

## Audit dan observability

| Tabel | Grain | Field kunci | Fungsi |
| --- | --- | --- | --- |
| `audit.pipeline_runs` | Satu pipeline run | `run_id` PK; status, waktu, metrik record | Audit run utama. |
| `audit.pipeline_stage_runs` | Satu stage pada satu run | `stage_run_id` PK; `run_id` FK | Durasi dan error tiap tahap. |
| `audit.source_ingestions` | Satu source file pada satu run | `source_ingestion_id` PK; `run_id` FK | Checksum, path, format, jumlah record. |
| `audit.source_snapshots` | Snapshot terbaru per pipeline/source | `(pipeline_name, source_name)` PK | Payload hash untuk incremental. |
| `audit.source_reconciliations` | Satu source pada satu run | `reconciliation_id` PK; `(run_id, source_name)` unik | Mode ingestion, scope/waktu/kelengkapan snapshot, business key yang ditemukan, serta jumlah fact yang dinonaktifkan. |
| `audit.data_quality_results` | Satu rule/source/run | `quality_result_id` PK; `run_id` FK | Jumlah kegagalan per rule dan severity. |
| `audit.rejected_records` | Satu baris transaksi yang ditolak dalam satu run | `rejected_record_id` PK; `run_id` FK | Payload asli, `source_order_id`, `source_line_number` jika valid, dan alasan penolakan. |
| `audit.pipeline_watermarks` | Watermark per pipeline/source | `(pipeline_name, source_name)` PK | Run sukses dan waktu proses terakhir. |

Kolom `audit.pipeline_runs.report_summary` bertipe `JSONB`. Nilainya dapat `NULL` pada run lama. Pada run baru, kolom ini menyimpan ringkasan untuk run tersebut: bagian `raw`, `quality_staging`, dan `warehouse`. Dashboard dan email membaca ringkasan yang sama agar angka laporan konsisten.

`warehouse.v_sales_detail` menambahkan `is_eligible_sale`, `returned_units`, dan `processed_refund_amount` per baris penjualan. View KPI/dashboard mengecualikan CANCELLED, memasukkan COMPLETED dan RETURNED, dan menghitung unit/order/line return rate secara terpisah. Nilai refund diagregasikan dahulu per baris sales agar tidak terjadi fan-out. Periode sales mengikuti tanggal order. `v_return_refund_kpi` mengelompokkan kejadian berdasarkan `return_date`; skema sumber belum memiliki tanggal aktual refund diproses.
