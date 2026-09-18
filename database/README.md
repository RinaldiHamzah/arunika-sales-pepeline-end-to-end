# Database Layer

The canonical database model uses four PostgreSQL schemas:

- `raw`: source-faithful CSV records and ingestion metadata.
- `staging`: validated canonical rows before warehouse key resolution.
- `warehouse`: date, product, customer, channel, payment, and sales fact tables.
- `audit`: pipeline runs, quality evidence, rejected records, and lineage.

Initialization order is numeric:

1. `schema/00_schemas.sql`
2. `schema/02_raw_tables.sql`
3. `schema/03_staging_tables.sql`
4. `schema/04_dimensions.sql`
5. `schema/05_fact_tables.sql`
6. `schema/06_audit_tables.sql`
7. `schema/07_analytics_views.sql`

`schema/00_airflow_database.sql` membuat database metadata Airflow terpisah pada
inisialisasi PostgreSQL pertama. Airflow tidak menyimpan tabel metadata di
database warehouse `ecommerce_sales`.

## Schema migrations

SQL pada folder `schema/` digunakan untuk bootstrap volume baru. Perubahan setelah
database berjalan dikelola dengan Alembic:

```powershell
alembic upgrade head
```

Buat revision baru setelah perubahan model:

```powershell
alembic revision -m "describe schema change"
alembic upgrade head
```

Service `pipeline` di Docker menjalankan `alembic upgrade head` sebelum ETL,
sehingga volume lama menerima perubahan schema tanpa dihapus.

## Security baseline

PostgreSQL hanya di-bind ke `127.0.0.1` secara default melalui
`POSTGRES_BIND_ADDRESS`. Password dibaca dari `.env` (yang di-ignore Git),
password default ditolak oleh konfigurasi Python, dan revision Alembic kedua
mencabut akses `PUBLIC`. Untuk deployment multi-user, role aplikasi harus dibuat
oleh cluster administrator sebagai `NOSUPERUSER NOCREATEDB NOCREATEROLE`; bootstrap
single-user Docker tetap menggunakan role pemilik database. Jika
database perlu diakses dari host lain, ubah bind address secara sadar dan batasi
aksesnya dengan firewall/network policy.

Model operasional tunggal menggunakan schema `raw`, `staging`, `warehouse`, dan
`audit`. Tidak ada schema star kedua; seluruh loader, view, dashboard, dan health
check menggunakan `warehouse`. Kontrak clean publik dimiliki
`pipeline/validation/contracts.py`; kolom warehouse menggunakan nama seperti
`source_name`, `source_order_id`, dan `sale_status`.

For a fresh local database:

```powershell
docker compose up -d
.\env\Scripts\python.exe -m pipeline.runner
```

The PostgreSQL init scripts run only when the data volume is first created. For
a schema change on an existing local volume, apply the changed SQL manually or
recreate the disposable development volume.
