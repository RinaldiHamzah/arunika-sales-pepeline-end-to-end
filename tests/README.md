# Panduan Pengujian

Folder ini berisi tes untuk pipeline ETL, dashboard, pelaporan, dan penerimaan end-to-end. Tes normal menggunakan data fixture/temporary dan tidak seharusnya mengubah database aplikasi. Tes PostgreSQL dan browser dijalankan terpisah melalui runner `tests/main.py`.

## Prasyarat

- Python dan dependensi proyek dari `requirements.txt` terpasang di virtual environment.
- Untuk tes integrasi PostgreSQL: Docker Desktop dan Docker Compose.
- Untuk tes browser: Node.js 22+ dan Chrome atau Edge.

Di PowerShell, aktifkan environment proyek:

```powershell
.\env\Scripts\Activate.ps1
```

## Menjalankan tes

Jalankan pemeriksaan standar yang direkomendasikan:

```powershell
python tests/main.py
```

Perintah tersebut menjalankan pemeriksaan keamanan skrip SQL, kontrak ekspor bersih, lalu semua tes pytest selain tes bertanda `integration`. Tes ini tidak memerlukan koneksi ke database aplikasi.

Pilihan lainnya:

```powershell
# Tes PostgreSQL end-to-end pada service database terisolasi ecommerce_sales_test
python tests/main.py --integration

# Tes smoke dashboard pada fixture lokal; tidak memakai API atau database produksi
python tests/main.py --browser

# Semua pemeriksaan: SQL, kontrak ekspor, pytest, PostgreSQL, dan browser
python tests/main.py --full
```

Untuk menjalankan satu modul tes secara langsung:

```powershell
$env:ARUNIKA_PYTEST_TEMP_ROOT = "$PWD\.test_runtime\pytest"
python -m pytest tests/test_data_quality.py -q
```

Ganti nama modul sesuai kelompok yang ingin diperiksa. `tests/conftest.py` memakai direktori sementara unik; pengaturan di atas membantu menghindari masalah izin direktori temporary pada Windows/OneDrive. `tests/main.py` menyiapkan direktori sementara proyek secara otomatis.

## Cakupan tes

| Modul | Cakupan utama |
| --- | --- |
| `test_contracts.py`, `test_extraction.py`, `test_sample_data.py` | Kontrak sumber, ekstraksi, fixture, dan integritas data contoh. |
| `test_data_quality.py`, `test_channel_quality_matrix.py`, `test_acceptance_fixtures.py` | Validasi tiap kanal, multi-item order, duplikat, pemetaan produk, dan fixture penerimaan. |
| `test_incremental.py`, `test_raw_incremental.py`, `test_fact_reconciliation.py` | Deteksi data baru/koreksi, idempotensi Raw, serta rekonsiliasi snapshot. |
| `test_promotions.py`, `test_returns.py` | Master promo dan diskon transaksi; validasi event retur/refund. |
| `test_staging_loader.py`, `test_warehouse_transform.py` | Transformasi dan pemuatan staging/warehouse. |
| `test_dashboard_ingestion.py` | Kontrak upload CSV dari dashboard dan penanganan kegagalan upload. |
| `test_reporting.py`, `test_alerts.py` | Ringkasan run, kualitas data, log, serta isi email laporan. |
| `test_analysis_format.py`, `test_database_bootstrap.py`, `test_source_manifest.py` | Format analisis, urutan/bootstrap database, dan deklarasi sumber/snapshot. |
| `test_integration_postgres.py` | Penerimaan end-to-end terhadap PostgreSQL terisolasi: migrasi, pipeline incremental, audit, dashboard/API, retur, KPI, dan integrasi orkestrasi. Tes ini bertanda `integration` dan tidak dijalankan oleh tes standar. |

## Catatan keamanan tes integrasi

`python tests/main.py --integration` menggunakan profil Docker `test` dan database `ecommerce_sales_test`, bukan database operasional `ecommerce_sales`. Tes integrasi memiliki pemeriksaan environment agar tidak berjalan jika koneksi bukan ke database uji yang secara eksplisit diizinkan. Jangan mengubah `DATABASE_URL` ke database produksi untuk menjalankan tes.

Jika tes gagal, runner berhenti pada langkah pertama yang gagal dan mengembalikan exit code bukan nol. Simpan output tes beserta nama tes yang gagal saat meninjau regresi.
