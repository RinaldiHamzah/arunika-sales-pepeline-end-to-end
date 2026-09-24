# Dokumentasi Database

Database utama proyek bernama `ecommerce_sales`. Metadata Airflow disimpan pada database terpisah bernama `airflow`.

Dokumen ini menjelaskan struktur schema, urutan bootstrap, serta perbedaan koneksi dari komputer lokal dan antar-container. Detail arti tabel dan kolom ada di [kamus data](../docs/data_dictionary.md).

## Schema PostgreSQL

| Schema | Isi |
| --- | --- |
| `raw` | Record source baru atau berubah dan metadata ingestion. |
| `staging` | Record canonical yang sudah valid sebelum resolusi foreign key. |
| `warehouse` | Star schema: dimensi dan `fact_sales`. |
| `audit` | Status run, kualitas data, record ditolak, snapshot, dan lineage. |

Jangan membuat schema warehouse kedua untuk source yang sama.

## Urutan bootstrap

1. `00_airflow_database.sql` — database metadata Airflow.
2. `00_schemas.sql` — schema aplikasi.
3. `01_extensions.sql` — extension `pgcrypto`.
4. `02_raw_tables.sql` — tabel raw dan ingestion.
5. `03_staging_tables.sql` — tabel staging.
6. `04_dimensions.sql` — tabel dimensi.
7. `05_fact_tables.sql` — tabel fakta.
8. `06_audit_tables.sql` — tabel audit dan kualitas data.
9. `07_analytics_views.sql` — view analitik.
10. `99_security_hardening.sql` — hardening privilege.

Script init Docker hanya berjalan saat volume pertama kali dibuat. Untuk schema yang sudah ada, gunakan Alembic:

```powershell
.\env\Scripts\python.exe -m alembic upgrade head
```

## Keamanan dan koneksi

- Password dibaca dari `.env`.
- PostgreSQL Docker hanya bind ke `127.0.0.1` secara default.
- Role production harus memakai hak minimum dan tidak memiliki `SUPERUSER`, `CREATEDB`, atau `CREATEROLE`.

Koneksi dari komputer lokal:

```text
Host     : 127.0.0.1
Port     : 5433
Database : ecommerce_sales
```

Antar-container memakai `postgres:5432`.
