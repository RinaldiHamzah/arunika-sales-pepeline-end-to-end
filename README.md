# End-to-End E-Commerce Sales Data Pipeline

Pipeline data engineering untuk mengingest CSV marketplace dan website dengan skema berbeda, memvalidasi serta menstandarkan data, kemudian memuat PostgreSQL data warehouse berbentuk star schema untuk analytics SQL dan dashboard Flask.

## Status

Pipeline end-to-end, quality layer, PostgreSQL warehouse, audit monitoring, Flask
dashboard, health check, and Airflow DAG are implemented. The supported local
runtime uses Docker PostgreSQL on host port `5433`.

CI menjalankan unit test, PostgreSQL integration test, dan Docker build pada
setiap push/pull request. Push ke branch `main` mempublikasikan image ke GitHub
Container Registry (`ghcr.io`) setelah seluruh test lulus.

Repeated runs are incremental: existing source rows and fact business keys are
skipped, while appended source rows are loaded once. Source corrections using an
existing row/key require an explicit correction policy and are not silently
overwritten.

## Menjalankan fondasi proyek

1. Salin `.env.example` menjadi `.env`, lalu ganti password database.
2. Buat dataset source:

   ```powershell
   .\env\Scripts\python.exe .\scripts\generate_sample_data.py
   ```

3. Jalankan database, pipeline sekali, dan dashboard:

   ```powershell
   docker compose up --build -d
   ```

4. Periksa status: `docker compose ps`. Service `pipeline` berjalan sekali setelah
   PostgreSQL sehat; `dashboard` tersedia di `http://127.0.0.1:8501`; Airflow
   tersedia di `http://127.0.0.1:8080`.

   Airflow 3 memakai `airflow api-server` sebagai pengganti proses webserver
   Airflow 2. Runtime lokal ini memakai Simple Auth Manager bawaan Airflow 3:
   username mengikuti `AIRFLOW_ADMIN_USERNAME` (default `admin`), sedangkan
   password dibuat saat API server pertama hidup. Ambil sekali dari
   `docker compose logs airflow-webserver`, kemudian simpan sebagai secret
   lokal; jangan commit atau membagikannya. `AIRFLOW_ADMIN_PASSWORD` tidak
   dipakai oleh Simple Auth Manager.
   pgAdmin bersifat opsional dan dapat diaktifkan dengan `docker compose --profile
   tools up -d pgadmin` pada `http://127.0.0.1:5050`.

5. Untuk menjalankan pipeline ulang setelah source berubah:

   ```powershell
   .\env\Scripts\python.exe -m pipeline.runner
   ```

### Menambahkan CSV baru melalui dashboard

1. Tambahkan `DASHBOARD_ADMIN_TOKEN` yang panjang dan rahasia pada `.env`.
2. Buka dashboard, isi **Admin token**, pilih source, lalu unggah batch CSV.
3. Header CSV harus persis sama dengan file source yang dipilih.
4. Klik **Run pipeline** dengan token yang sama.

Upload menambahkan baris ke `data/source/<source>.csv`; pipeline kemudian
menyimpan snapshot raw baru, memvalidasi data, dan hanya memuat fact baru atau
fact yang berubah. Semua service Docker membaca folder host `data/source/`
melalui volume mount, sehingga file baru tidak membutuhkan rebuild image.

### Monitoring scheduler dan operasi

Bagian **Settings** pada dashboard, dengan admin token, menampilkan riwayat
sepuluh pipeline run terbaru, status, durasi, volume data, dan metrik quality.
Tombol **Run pipeline** menampilkan tahap aktif dari audit database secara
real-time. Pengaturan jadwal tetap dikelola oleh Airflow di environment
orchestration, bukan dari dashboard.

Perubahan schema pada database yang sudah berjalan menggunakan Alembic:

```powershell
alembic upgrade head
```

Untuk log terstruktur yang siap dikumpulkan ke platform observability, set
`LOG_FORMAT=json` di `.env`. Mode debug dashboard tetap nonaktif secara default;
gunakan `FLASK_DEBUG=1` hanya untuk pengembangan lokal.

Freshness source dapat diperiksa sebelum run:

```powershell
.\env\Scripts\python.exe .\scripts\check_freshness.py
```

Untuk melihat performa pipeline lengkap dari audit PostgreSQL dalam format JSON:

```powershell
.\env\Scripts\python.exe .\scripts\monitor_pipeline.py
```

Gunakan `--follow 10` untuk refresh setiap 10 detik. Log lokal tersimpan di
`logs/pipeline.log` dan `logs/dashboard.log`; gunakan `LOG_FORMAT=json` untuk
log terstruktur.

Semua timestamp pada backend, session PostgreSQL, structured log, dan dashboard
menggunakan **WIB (`Asia/Jakarta`, offset `+07:00`)**. Atur `APP_TIMEZONE` di
`.env` bila kebijakan waktu perlu diubah secara terkontrol.

Set `ALERT_WEBHOOK_URL` untuk mengirim notifikasi kegagalan pipeline ke webhook
monitoring pilihan Anda. Alert bersifat opsional dan tidak membuat ETL gagal bila
endpoint notifikasi sedang tidak tersedia.

Security baseline: PostgreSQL hanya tersedia di localhost secara default,
password tidak disimpan di repository, dan `alembic upgrade head` menerapkan
hardening privilege pada volume lama.

   Pipeline membuat audit run, membaca seluruh source, lalu menyimpan source record tanpa perubahan ke schema `raw` beserta metadata file (nama, path, checksum SHA-256, format, dan jumlah record).

## Dataset source

Generator menghasilkan `shopee.csv`, `tokopedia.csv`, `website.csv`, `offline.csv`, dan `product.csv` di `data/source/`. Katalog menggunakan SKU dan harga sintetis yang terinspirasi brand Paragon—Wardah, Emina, Make Over, Kahf, LABORE, Instaperfect, Crystallure, TAVI, Biodef, dan Wonderly—bukan katalog atau harga resmi. Data dibuat deterministik serta sengaja memuat duplicate, nilai hilang, harga/kuantitas invalid, format tanggal berbeda, product-name variant, dan status invalid untuk menguji data-quality layer.

## Analisis dan Data Quality

Keenam notebook di `analisis/` memakai aturan bersama untuk missing value,
duplicate, invalid value, tanggal, tipe data, serta product mapping.
Analisis mengikuti file aktif `product.csv`, `shopee.csv`, `tokopedia.csv`,
`website.csv`, dan `offline.csv` tanpa mengubah sumber. Tidak perlu menjalankan
generator untuk analisis ini. Detail kebijakan: [docs/data_quality.md](docs/data_quality.md).

```powershell
.\env\Scripts\python.exe -m pipeline.validation.analysis
```

Hasil utama tersimpan di `data/processed/clean/`. Semua transaksi memakai 12 kolom
sesuai contoh: `order_id, product_id, product_name, kategori, quantity, total_harga,
tanggal_order, kota, channel, status, customer_email, harga_satuan`.
Gunakan Run All pada `analisis/analisa.ipynb` untuk overview; semua notebook memakai
urutan Missing value, Duplicate, Invalid value, Date format, Data type, Product consistency.

## Validasi kontrak clean sebelum publish

Sebelum notebook atau export final dipublikasikan, jalankan validator ini untuk memastikan semua file clean sesuai kontrak final tanpa `customer_id`:

```powershell
.\env\Scripts\python.exe .\scripts\check_clean_contract.py
```

Jika script mengembalikan `Clean contract check OK`, maka semua file CSV di `data/processed/clean/` sudah memenuhi schema final yang dipakai untuk analytics.

## Arsitektur target

`CSV sources -> raw PostgreSQL -> validation -> staging -> warehouse star schema -> SQL analytics / Flask dashboard`

## Menjalankan dashboard

Pastikan PostgreSQL dan pipeline sudah berjalan, lalu jalankan:

```powershell
.\env\Scripts\python.exe dashboard\flask.py
```

Buka `http://127.0.0.1:8501`. Dashboard Flask membaca analytics view PostgreSQL,
menyediakan filter periode, channel, status, kategori, brand, SKU, export CSV,
upload batch CSV tervalidasi, dan run pipeline terproteksi admin token.

## Integration test PostgreSQL terisolasi

Jangan jalankan acceptance test pada database development. Project menyediakan
database sementara bernama `ecommerce_sales_test` melalui Docker profile
`test`:

```powershell
docker compose --profile test run --rm integration-tests
```

Service tersebut menjalankan skenario raw → staging → dimension → fact,
membuktikan rerun idempotent, lalu menambahkan 20 transaksi baru pada database
test saja. Tidak ada tabel atau data pada `ecommerce_sales` yang dipakai.

## Orkestrasi Airflow

DAG berada di `airflow/dags/orchestration.py` dan menjalankan pipeline
harian lalu warehouse health check. Airflow tidak didukung sebagai runtime native
Windows; jalankan scheduler/webserver melalui Docker atau WSL2 dengan Python
dan Airflow yang kompatibel. Eksekusi manual tetap tersedia melalui:

```powershell
.\env\Scripts\python.exe -m pipeline.runner
.\env\Scripts\python.exe .\scripts\check_warehouse.py
```

Pada startup, service `airflow-db-bootstrap` memastikan database metadata
`airflow` tersedia bahkan bila volume PostgreSQL dibuat sebelum Airflow
ditambahkan. Cek kesehatan API server melalui
`http://127.0.0.1:8080/api/v2/monitor/health`.
