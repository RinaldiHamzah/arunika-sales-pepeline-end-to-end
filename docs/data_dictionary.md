# Kamus Data Warehouse

## `warehouse.fact_sales`

Grain: satu produk dalam satu transaksi source. Primary key: `sales_key`. Business key: `(source_name, source_order_id, source_line_number)`.

| Kolom | Tipe | Keterangan |
| --- | --- | --- |
| `sales_key` | BIGINT | Surrogate key fact. |
| `source_name` | VARCHAR | `SHOPEE`, `TOKOPEDIA`, `WEBSITE`, atau `OFFLINE_STORE`. |
| `source_order_id` | TEXT | ID transaksi dari source. |
| `source_line_number` | INTEGER | Nomor baris produk; saat ini umumnya `1`. |
| `date_key` | INTEGER | Foreign key ke `dim_date`. |
| `product_key` | BIGINT | Foreign key ke `dim_product`. |
| `customer_key` | BIGINT | Foreign key opsional ke `dim_customer`. |
| `channel_key` | SMALLINT | Foreign key ke `dim_channel`. |
| `payment_key` | SMALLINT | Foreign key opsional ke `dim_payment`. |
| `sale_status` | VARCHAR | `COMPLETED`, `CANCELLED`, atau `RETURNED`. |
| `quantity` | INTEGER | Jumlah unit positif. |
| `unit_price` | NUMERIC(14,2) | Harga satuan transaksi. |
| `gross_amount` | NUMERIC(16,2) | `quantity × unit_price`. |
| `discount_amount` | NUMERIC(16,2) | Diskon tervalidasi; saat ini nol. |
| `net_amount` | NUMERIC(16,2) | `gross_amount - discount_amount`. |
| `source_record_hash` | CHAR(64) | Hash isi record untuk koreksi dan idempotensi. |
| `is_source_active` | BOOLEAN | Status source; record tidak dihapus fisik. |

## Dimensi

| Tabel | Key | Isi |
| --- | --- | --- |
| `warehouse.dim_product` | `product_key`, unik `sku` | SKU, nama, brand, kategori, harga standar. |
| `warehouse.dim_date` | `date_key` | Atribut kalender. |
| `warehouse.dim_customer` | `customer_key`, unik `customer_nk` | Identitas pelanggan per source dan kota terverifikasi. |
| `warehouse.dim_channel` | `channel_key`, unik `channel_code` | Nama dan tipe channel. |
| `warehouse.dim_payment` | `payment_key`, unik `payment_method` | Metode pembayaran canonical. |

## Staging dan audit

| Tabel | Isi |
| --- | --- |
| `staging.stg_sales` | Record canonical valid dan lineage raw sebelum resolusi foreign key. |
| `audit.pipeline_runs` | Status, durasi, dan metrik pipeline. |
| `audit.pipeline_stage_runs` | Status serta durasi setiap tahap. |
| `audit.data_quality_results` | Ringkasan rule kualitas data per run. |
| `audit.rejected_records` | Payload yang ditolak dan alasannya. |
| `audit.pipeline_watermarks` | Penanda source/run sukses terakhir. |
| `audit.source_ingestions` | Checksum, path, format, dan jumlah record source. |
| `audit.source_snapshots` | Fingerprint source untuk incremental loading. |
