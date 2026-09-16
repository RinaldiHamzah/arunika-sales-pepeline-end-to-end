# End-to-End E-Commerce Sales Data Pipeline

Pipeline data engineering untuk mengingest CSV marketplace dan website dengan skema berbeda, memvalidasi serta menstandarkan data, kemudian memuat PostgreSQL data warehouse berbentuk star schema untuk analytics SQL dan dashboard Streamlit.

## Status

Fase 1 selesai: infrastruktur PostgreSQL lokal, konfigurasi, struktur repository, dan generator dataset reproducible. Fase berikutnya menambahkan raw/staging/warehouse, ETL, Airflow, dashboard, dan dokumentasi teknis.

## Menjalankan fondasi proyek

1. Salin `.env.example` menjadi `.env`, lalu ganti password database.
2. Buat dataset source:

   ```powershell
   python data_generator/generate_data.py
   ```

3. Jalankan PostgreSQL:

   ```powershell
   docker compose up -d
   ```

4. Periksa status: `docker compose ps`.

5. Setelah PostgreSQL sehat, jalankan extract dan raw ingestion:

   ```powershell
   python -m pipeline.runner
   ```

   Pipeline membuat audit run, membaca seluruh source, lalu menyimpan source record tanpa perubahan ke schema `raw` beserta metadata file (nama, path, checksum SHA-256, format, dan jumlah record).

## Dataset source

Generator menghasilkan `shopee.csv`, `tokopedia.json`, `website.csv`, `offline_store.csv`, dan `product_master.csv` di `data/source/`. Katalog menggunakan SKU dan harga sintetis yang terinspirasi brand Paragon—Wardah, Emina, Make Over, Kahf, LABORE, Instaperfect, Crystallure, TAVI, Biodef, dan Wonderly—bukan katalog atau harga resmi. Data dibuat deterministik serta sengaja memuat duplicate, nilai hilang, harga/kuantitas invalid, format tanggal berbeda, product-name variant, dan status invalid untuk menguji data-quality layer.

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

## Arsitektur target

`CSV sources -> raw PostgreSQL -> validation -> staging -> warehouse star schema -> SQL analytics / Streamlit`
