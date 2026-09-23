# Arunika Beauty — E-Commerce Sales Data Pipeline

Proyek ini menggabungkan data Shopee, Tokopedia, website, toko offline, dan Product Master ke PostgreSQL. Pipeline membersihkan data, menyimpan audit, memuat warehouse berbentuk star schema, lalu menyajikan analitik melalui dashboard Flask dan Airflow.

```text
CSV source → raw → validasi → staging → warehouse → analytics → dashboard
```

Dokumentasi: [arsitektur](docs/architecture.md), [kualitas data](docs/data_quality.md), [kamus data](docs/data_dictionary.md), [ERD](docs/erd.md), [runbook](docs/technical_runbook.md), [database](database/README.md), dan [dashboard](dashboard/README.md).

## Menjalankan proyek

1. Salin `.env.example` menjadi `.env`, lalu isi password dan token. Jangan commit `.env`.
2. Jalankan service:

   ```powershell
   docker compose up -d --build
   ```

3. Periksa status dengan `docker compose ps`.
4. Buka Dashboard di `http://127.0.0.1:8501` dan Airflow di `http://127.0.0.1:8080`.

PostgreSQL Docker hanya tersedia dari komputer lokal melalui `127.0.0.1:5433`.

## Menjalankan pipeline

```powershell
.\env\Scripts\python.exe -m pipeline.runner
.\env\Scripts\python.exe .\scripts\check_warehouse.py
```

Hasil run tersimpan di `audit.pipeline_runs`, `logs/pipeline.log`, dashboard, dan email jika SMTP dikonfigurasi. Source yang identik akan dilaporkan sebagai `skipped_unchanged_records`; artinya tidak ada data baru yang dimuat.

Periksa freshness source bila diperlukan:

```powershell
.\env\Scripts\python.exe .\scripts\check_freshness.py
```

## Menambahkan CSV baru

Melalui dashboard: buka **Settings**, pilih source, unggah CSV dengan header yang sama, masukkan `DASHBOARD_ADMIN_TOKEN`, lalu klik **Upload CSV** dan **Run pipeline**.

Atau tambahkan baris baru langsung ke salah satu file berikut, kemudian jalankan runner:

```text
data/source/product.csv
data/source/shopee.csv
data/source/tokopedia.csv
data/source/website.csv
data/source/offline.csv
```

Jangan mengubah header source tanpa memperbarui kontrak dan extractor terkait.

## Airflow dan email

DAG `ecommerce_sales_pipeline` berada di `airflow/orchestration.py` dan berjalan setiap hari pukul **13.00 WIB** (`0 13 * * *`). Pastikan DAG tidak paused dan service scheduler serta dag processor berjalan.

Run manual, run dashboard, dan run Airflow dapat mengirim laporan email. Contoh konfigurasi `.env`:

```env
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USE_TLS=true
SMTP_USERNAME=alamat-pengirim@gmail.com
SMTP_PASSWORD=gmail_app_password
SMTP_FROM=alamat-pengirim@gmail.com
PIPELINE_REPORT_RECIPIENTS=penerima1@gmail.com,penerima2@gmail.com
```

Untuk Gmail, gunakan **App Password**, bukan password akun Gmail biasa.

## Database dan migration

```text
raw       : payload source dan metadata ingestion
staging   : data canonical tervalidasi
warehouse : dimensi dan fact sales
audit     : run, kualitas data, lineage, dan snapshot
```

File SQL dalam `database/schema/` dipakai pada volume PostgreSQL baru. Untuk database yang sudah ada, terapkan migration:

```powershell
.\env\Scripts\python.exe -m alembic upgrade head
```

## Pengujian

```powershell
.\env\Scripts\python.exe .\tests\main.py
```

Untuk test lengkap, termasuk PostgreSQL terisolasi dan browser smoke test:

```powershell
.\env\Scripts\python.exe .\tests\main.py --full
```

Test memakai database `ecommerce_sales_test` yang terpisah dari warehouse development, tidak mengubah source utama, dan tidak mengirim email.

## Data sample dan analisis

Data sample berada di `data/source/` dan dibuat untuk simulasi, bukan katalog atau harga resmi. Untuk membuat export bersih dan laporan kualitas data:

```powershell
.\env\Scripts\python.exe -m pipeline.validation.analysis
.\env\Scripts\python.exe .\scripts\check_clean_contract.py
```

Hasilnya tersedia di `data/processed/clean/`.

## Keamanan dan waktu

- Password, token, dan App Password hanya disimpan di `.env`.
- PostgreSQL hanya bind ke `127.0.0.1` secara default.
- Aksi upload dan menjalankan pipeline dari dashboard membutuhkan admin token.
- Database, log, dashboard, dan Airflow memakai `Asia/Jakarta` atau WIB.
