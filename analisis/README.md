# Analisis Data dan Data Quality

Folder ini berisi notebook untuk memeriksa karakteristik data sumber dan melihat hasil aturan kualitas sebelum data dipakai dalam analisis. Notebook menggunakan fungsi validasi yang sama dengan proses export pipeline, sehingga aturan missing value, duplikat, nilai tidak valid, tanggal, tipe data, dan pemetaan produk tetap konsisten.

## Daftar notebook

| Notebook | Cakupan |
| --- | --- |
| `analisa.ipynb` | Semua sumber transaksi dan Product Master dalam satu pemeriksaan. Gunakan notebook ini untuk melihat ringkasan gabungan. |
| `shopee.ipynb` | Pemeriksaan khusus transaksi Shopee. |
| `tokopedia.ipynb` | Pemeriksaan khusus transaksi Tokopedia. |
| `website.ipynb` | Pemeriksaan khusus transaksi Website. |
| `offline.ipynb` | Pemeriksaan khusus transaksi Offline Store. |
| `product.ipynb` | Pemeriksaan Product Master. |

Setiap notebook menampilkan hasil pemeriksaan seperti nilai kosong, duplikat, nilai dan tipe data, tanggal, pemetaan produk, serta ringkasan data bersih. Business key transaksi saat ini menggunakan `(channel, order_id)` karena data contoh memiliki satu item per order. Jika sumber menyediakan beberapa item dalam satu order, identitas baris item perlu ditambahkan ke key.

## Menjalankan notebook

1. Pastikan dependensi proyek sudah terpasang di virtual environment `env`.
2. Buka Jupyter Notebook atau JupyterLab dari root proyek.
3. Pilih kernel dari virtual environment `env`.
4. Buka notebook yang sesuai, lalu pilih **Run All**.

Notebook mencari root proyek dari lokasi kerja saat dibuka. Karena itu, buka Jupyter dari root repository atau dari subfolder `analisis/`.

Untuk menjalankan analisis dan membuat export tanpa membuka notebook:

```powershell
.\env\Scripts\python.exe -m pipeline.validation.analysis
```

Perintah tersebut memproses semua sumber dan menyimpan hasil di `data/processed/`. File yang dihasilkan mencakup `product.csv`, file transaksi per sumber, `sales.csv`, `summary.csv`, dan `quality_issues.csv`. File export dapat diperbarui saat perintah dijalankan kembali; file di `data/source/` tidak ditimpa.

## Cara membaca hasil

- **Missing value** menunjukkan field kosong. Field wajib yang kosong membuat baris ditolak; field opsional tetap kosong dan dapat dicatat sebagai peringatan.
- **Duplicate** memakai business key. Satu salinan data identik dipertahankan, sedangkan salinan berikutnya dicatat sebagai duplikat. Konflik pada key yang sama ditolak agar sistem tidak memilih versi secara sembarang.
- **Invalid value dan tipe data** mencakup quantity, harga, total transaksi, status, tanggal, dan kolom yang perlu dikonversi ke tipe standar.
- **Product mapping** mencocokkan nama atau SKU dari transaksi dengan Product Master. Produk yang tidak dapat dipetakan tidak masuk ke data transaksi bersih.
- Satu baris dapat memiliki lebih dari satu temuan. Karena itu, total issue tidak selalu sama dengan jumlah baris yang ditolak.

Notebook ini adalah sarana analisis dan export lokal, bukan pengganti pipeline operasional. Menjalankannya tidak memuat data ke PostgreSQL. Untuk memuat data ke Raw, Staging, dan Warehouse, gunakan pipeline melalui dashboard, Airflow, atau perintah terminal yang dijelaskan di [README utama](../README.md).

Aturan lengkap dan contoh laporan tersimpan di [Kebijakan Kualitas Data](../docs/data_quality.md). Bentuk kolom export dijelaskan dalam [Kamus Data](../docs/data_dictionary.md).
