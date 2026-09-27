# Database dan Struktur Warehouse

Database aplikasi bernama `ecommerce_sales`. PostgreSQL menyimpan data sumber, hasil validasi, data transaksi analitik, serta catatan eksekusi pipeline. Metadata Airflow berada di database terpisah bernama `airflow`.

Dokumen ini menjelaskan susunan database dan cara memeriksanya. Definisi kolom, tipe data, primary key, foreign key, dan grain tiap tabel tersedia di [Kamus Data](../docs/data_dictionary.md). Hubungan antar tabel ditampilkan pada [ERD](../docs/erd.md).

## Susunan schema

| Schema | Isi dan kegunaan |
| --- | --- |
| `raw` | Record baru atau berubah dalam format yang mengikuti sumber, termasuk payload asli dan metadata file/baris. Nilai yang belum bersih tetap dipertahankan agar dapat ditelusuri. |
| `staging` | Transaksi yang lolos pemeriksaan dan sudah diseragamkan sebelum kunci dimensi diselesaikan. |
| `warehouse` | Star schema untuk pelaporan: fact transaksi dan dimensi tanggal, produk, customer, kanal, serta pembayaran. |
| `audit` | Status run dan tahap, sumber yang diproses, snapshot incremental, watermark, hasil pemeriksaan kualitas, serta record yang ditolak. |

Raw menyimpan perubahan yang diterima pada suatu run; tabel raw bukan salinan baru seluruh file pada setiap run. Baris yang identik dengan snapshot sukses terakhir dilewati sebelum raw load. Jika tidak ada perubahan, tahap quality check, staging, dan warehouse tidak dijalankan ulang.

## Model warehouse

Grain `warehouse.fact_sales` adalah satu baris produk pada satu transaksi sumber. Identitas transaksi lintas kanal ditentukan oleh `(source_name, source_order_id, source_line_number)`. Saat ini `source_line_number` bernilai `1`, karena sumber contoh belum menyediakan ID baris produk yang stabil.

`fact_sales` menyimpan jumlah unit, harga, penjualan kotor, diskon, penjualan bersih, status, hash sumber, serta foreign key ke dimensi. Dimensi menyediakan konteks tanggal, produk, customer, kanal, dan pembayaran. Skema ini memisahkan ukuran transaksi dari atribut deskriptif agar query analitik dapat mengelompokkan penjualan berdasarkan waktu, produk, atau kanal.

Tabel transaksi utama:

| Tabel | Grain / fungsi |
| --- | --- |
| `raw.shopee_orders` | Satu baris sumber Shopee yang baru atau berubah. |
| `raw.tokopedia_transactions` | Satu baris sumber Tokopedia yang baru atau berubah. |
| `raw.website_transactions` | Satu baris sumber Website yang baru atau berubah. |
| `raw.offline_store_sales` | Satu baris sumber Offline Store yang baru atau berubah. |
| `raw.product_master` | Satu baris referensi produk yang baru atau berubah. |
| `staging.stg_sales` | Satu transaksi canonical yang lolos pemeriksaan. |
| `warehouse.fact_sales` | Satu baris produk/transaksi yang siap untuk analitik. |

Raw dan audit tidak selalu memakai foreign key langsung ke tabel lain. Pipeline mempertahankan `run_id`, ID record sumber, business key, serta hash sebagai lineage operasional. Foreign key fact ke dimensi ditegakkan oleh PostgreSQL.

## Bootstrap dan migration

Pada volume PostgreSQL yang masih baru, script di `database/schema/` dijalankan dalam urutan berikut:

1. `00_airflow_database.sql` membuat database metadata Airflow.
2. `00_schemas.sql` membuat schema aplikasi.
3. `01_extensions.sql` menyiapkan extension yang dibutuhkan.
4. `02_raw_tables.sql` membuat tabel sumber.
5. `03_staging_tables.sql` membuat tabel staging.
6. `04_dimensions.sql` membuat dimensi.
7. `05_fact_tables.sql` membuat tabel fact.
8. `06_audit_tables.sql` membuat tabel audit dan quality.
9. `07_analytics_views.sql` membuat view analitik.
10. `99_security_hardening.sql` mengatur hak akses database.

Script init Docker berjalan saat volume database pertama kali dibuat. Untuk memperbarui database yang sudah berisi data, gunakan migration Alembic; jangan menghapus volume sebagai cara rutin memperbarui schema.

```powershell
.\env\Scripts\python.exe -m alembic upgrade head
```

## Koneksi

Di konfigurasi bawaan, PostgreSQL hanya tersedia dari komputer lokal pada `127.0.0.1:5433`. Di dalam Docker Compose, service lain memakai hostname `postgres` dan port `5432`.

```text
Host lokal       : 127.0.0.1
Port lokal       : 5433
Host container   : postgres
Port container   : 5432
Database aplikasi: ecommerce_sales
Username         : nilai POSTGRES_USER dari .env
Password         : nilai POSTGRES_PASSWORD dari .env
```

Jangan menaruh password langsung ke perintah atau dokumentasi yang akan dibagikan. Nilainya dibaca dari `.env`.

## Memeriksa isi database

Daftar tabel aplikasi:

```powershell
docker compose exec postgres psql -U ecommerce_user -d ecommerce_sales -c "SELECT table_schema, table_name FROM information_schema.tables WHERE table_schema IN ('raw','staging','warehouse','audit') AND table_type = 'BASE TABLE' ORDER BY table_schema, table_name;"
```

Jumlah baris per tabel transaksi utama:

```sql
SELECT 'raw.shopee_orders' AS tabel, COUNT(*) FROM raw.shopee_orders
UNION ALL SELECT 'raw.tokopedia_transactions', COUNT(*) FROM raw.tokopedia_transactions
UNION ALL SELECT 'raw.website_transactions', COUNT(*) FROM raw.website_transactions
UNION ALL SELECT 'raw.offline_store_sales', COUNT(*) FROM raw.offline_store_sales
UNION ALL SELECT 'raw.product_master', COUNT(*) FROM raw.product_master
UNION ALL SELECT 'staging.stg_sales', COUNT(*) FROM staging.stg_sales
UNION ALL SELECT 'warehouse.fact_sales', COUNT(*) FROM warehouse.fact_sales;
```

Raw Product Master dihitung terpisah dari transaksi penjualan. Jumlah pada tabel raw adalah isi tabel saat ini, sedangkan laporan pipeline menunjukkan jumlah yang diproses pada satu run; keduanya menjawab pertanyaan yang berbeda.

Untuk melihat hasil pemeriksaan kualitas terbaru, gunakan script proyek:

```powershell
.\env\Scripts\python.exe .\scripts\report_data_quality.py
```

Laporan historis dan contoh query tersedia pada [Kebijakan Kualitas Data](../docs/data_quality.md).

## SQL analytics

View SQL tersedia di PostgreSQL dan menjadi sumber metrik dashboard serta pemeriksaan analitik:

```text
warehouse.v_sales_detail
warehouse.v_sales_kpi
warehouse.v_sales_monthly_kpi
warehouse.v_sales_channel_kpi
warehouse.v_top_product_kpi
warehouse.v_sales_status_kpi
audit.v_data_quality_by_rule
audit.v_data_quality_report
```

Contoh query:

```sql
SELECT * FROM warehouse.v_sales_kpi;
SELECT * FROM warehouse.v_sales_monthly_kpi ORDER BY month_start;
SELECT * FROM warehouse.v_sales_channel_kpi ORDER BY net_sales_completed DESC;
SELECT * FROM warehouse.v_top_product_kpi ORDER BY net_sales_completed DESC LIMIT 10;
```

Dashboard juga menjalankan agregasi SQL pada `warehouse.v_sales_detail` agar filter periode, kanal, status, kategori, merek, dan produk diterapkan di database. Aturan gross, net, AOV, dan return rate dijelaskan dalam [README utama](../README.md) dan definisi view berada di `database/schema/07_analytics_views.sql`.

## Keamanan

- Jangan commit `.env`, password, token admin, atau App Password email.
- PostgreSQL hanya bind ke loopback secara default. Jangan membuka port database ke internet.
- Pertahankan hak akses minimum untuk role aplikasi dan hindari hak `SUPERUSER`, `CREATEDB`, atau `CREATEROLE` pada akun operasional.
- Gunakan database test terpisah saat menjalankan integration test.
