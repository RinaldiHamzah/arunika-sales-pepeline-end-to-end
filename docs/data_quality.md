# Data Quality — kebijakan v1.0

## Kontrak data canonical

`pipeline.validation.contracts` adalah satu-satunya sumber definisi kontrak yang
dipakai oleh validasi, notebook analysis, dan loader berikutnya. Modul tersebut
menetapkan schema raw, schema clean, grain, key bisnis, status valid, serta
disposition record.

| Area | Kontrak |
| --- | --- |
| Raw source | `product.csv`, `shopee.csv`, `tokopedia.csv`, `website.csv`, `offline.csv`; setiap file memiliki kolom wajib yang didefinisikan oleh `SOURCE_SPECS` |
| Clean transaction | `order_id, product_id, product_name, kategori, quantity, total_harga, tanggal_order, kota, channel, status, customer_email, harga_satuan` |
| Clean product | `product_id, product_name, brand, kategori, harga_satuan` |
| Grain | Satu baris per order; `line_number=1` karena source saat ini belum menyediakan line ID |
| Business key | `(source, order_id, line_number)` pada internal layer; master menggunakan `sku` |
| Status valid | `COMPLETED`, `CANCELLED`, `RETURNED` |
| Clean | Record valid pertama untuk business key |
| Duplicate | Record valid berikutnya dengan business key yang sama |
| Rejected | Record dengan error atau seluruh versi pada conflicting duplicate |

Field source-only tidak tersedia pada clean transaction. Record rejected dan
duplicate tidak dibuang: metadata, alasan, checksum, serta raw payload disimpan
di laporan evidence untuk audit dan perbaikan sumber.

## Format notebook yang disederhanakan

Semua notebook memakai enam bagian yang sama: Missing value, Duplicate, Invalid
value, Date format, Data type, Product consistency. Satu tabel bersih ditampilkan
di akhir. `pipeline.validation.analysis` menyediakan format tampilan, sedangkan
`pipeline.validation.data_quality` tetap menjadi mesin validasi bersama.

Kolom transaksi persis mengikuti contoh pengguna:

```text
order_id,product_id,product_name,kategori,quantity,total_harga,tanggal_order,kota,channel,status,customer_email,harga_satuan
```

`product_id` adalah SKU master asli, bukan ID P001 buatan baru. `total_harga`
adalah gross amount; status ditampilkan Completed/Cancelled/Returned. Contoh
lampiran digunakan sebagai acuan format, bukan mengganti katalog atau menambahkan
status Pending/Shipped ke kebijakan dataset saat ini. `kota` menunjukkan kota
pelanggan online atau kota outlet offline, sesuai channel; kota Website tetap kosong.
Kolom `customer_id` tidak disertakan pada hasil bersih keempat channel maupun
file gabungan karena tidak tersedia pada semua sumber. Email yang tidak tersedia
tetap null. Identitas, nama, dan kategori
produk mengikuti master; kode SPF/PA++++ dan shade tidak diubah ke title case.
Raw layer tetap menyimpan payload sumber apa adanya untuk audit dan traceability,
tetapi `customer_id` tidak diteruskan ke canonical clean layer, warehouse, maupun
dataset analitis.

Master memakai `product_id,product_name,brand,kategori,harga_satuan` karena tidak
memiliki atribut transaksi. CSV sumber tetap utuh.

Semua notebook `analisis/` memakai `pipeline.validation.data_quality`, sehingga aturan
dan hasilnya konsisten. Ini penerapan praktik data engineering yang dapat diuji:
completeness, uniqueness, validity, consistency, referential integrity, dan lineage.
Dokumen ini tidak mengklaim sertifikasi ISO atau bahwa kualitas bisnis dapat dijamin
hanya lewat pemeriksaan sintaks. Akurasi harga aktual dan kebenaran identitas pelanggan
memerlukan konfirmasi pemilik data.

## Sumber yang digunakan

Hanya lima file aktif yang dibaca: `product.csv`, `shopee.csv`, `tokopedia.csv`,
`website.csv`, `offline.csv` di `data/source/`. Nama ini mengikuti notebook dan data
terbaru, bukan nama generator/JSON pada fase sebelumnya. File salinan tidak otomatis
diikutkan. File sumber tidak diubah atau diregenerasi. Kolom tambahan dipertahankan
dalam raw payload record bermasalah; kolom di luar kontrak tidak masuk dataset bersih.
Kolom wajib hilang, header duplikat, atau CSV rusak menghentikan proses secara eksplisit.

## Aturan dan treatment

| Pemeriksaan | Aturan | Treatment |
| --- | --- | --- |
| Missing value | Blank/whitespace, NA, N/A, NULL, NONE, NAN dikenali sebagai kosong | Field transaksi wajib ditolak; customer/payment opsional tetap null dengan warning |
| Field wajib | ID order, tanggal, produk, quantity, unit price, status; seluruh kolom master | Tidak mengisi dengan nilai tebakan |
| Total Website | `total_amount` wajib dan sama dengan quantity × unit price | Missing atau mismatch ditolak; model saat ini belum memuat diskon |
| Quantity | Bilangan bulat positif, dalam rentang INTEGER PostgreSQL | Nol, negatif, pecahan, nonnumerik ditolak |
| Uang | Decimal positif, maksimum 2 desimal dan rentang NUMERIC(14,2) | Tidak membulatkan diam-diam; harga nol/free sample belum diizinkan |
| Status | COMPLETED, CANCELLED, RETURNED | Nilai lain dikarantina sampai ada aturan bisnis yang disetujui |
| Tanggal | Shopee/Tokopedia DD/MM/YYYY; Website MMM DD, YYYY (bulan Inggris); Offline DD-MMM-YYYY; ISO YYYY-MM-DD diterima semua | Parse eksplisit; tanggal mustahil atau format lain ditolak |
| Produk | SKU atau nama dengan perbedaan case, spasi, underscore, hyphen | Nama, brand, kategori diambil persis dari master tervalidasi |
| Typo/produk asing | Tidak cocok dengan master setelah normalisasi aman | UNMAPPED_PRODUCT; perlu alias yang ditinjau, tidak fuzzy-match otomatis |
| Harga beda master | Harga transaksi positif tetapi berbeda harga referensi | Warning, harga sumber tetap dipertahankan karena mungkin promo |
| Duplicate sama | Key sama dan seluruh nilai kanonis sama | Simpan satu; sisanya ke duplicates |
| Duplicate konflik | Key sama tetapi nilai kanonis berbeda | Semua versi masuk rejected; tidak memilih keep-first/last |
| Email | Pemeriksaan struktur sederhana bila tersedia | Email invalid dijadikan null dengan warning; bukan verifikasi deliverability |

Kota toko disimpan sebagai `store_city`, terpisah dari `customer_city`. Pelanggan
offline yang tidak tersedia tidak dibuat-buat. ID pelanggan antar-channel tidak
digabung hanya karena namanya sama. Payment dan kota yang dikenal memakai ejaan
kanonis; payment asing diberi warning. Nama pelanggan mempertahankan kapitalisasi
sumber setelah normalisasi whitespace, untuk menghindari perubahan nama yang tidak sah.

## Keseragaman karakter dan tipe

- Unicode NFKC dan whitespace trim/collapse diterapkan pada teks.
- Nama kolom hasil memakai `snake_case`, SKU master uppercase, status uppercase
  secara internal dan Completed/Cancelled/Returned pada format hasil notebook.
- Nama produk memakai kapitalisasi master, bukan `.title()` yang merusak LABORE/SPF.
- Kode shade, angka, ukuran, dan tanda `+` tetap dibedakan. `PA+++` bukan `PA++++`.
- Identifier bertipe string (leading zero tetap ada), quantity nullable `Int64`.
- Tanggal bertipe datetime dan diekspor `YYYY-MM-DD`; input hanya tanggal kalender,
  tidak diberi timezone atau jam transaksi fiktif.
- Uang menggunakan `decimal.Decimal` (dtype object di Pandas), diekspor dua desimal.
  CSV tidak menyimpan tipe: konsumen harus memuat tanggal, integer, dan uang secara eksplisit.

## Grain, duplicate, dan rekonsiliasi

Grain dataset saat ini diasumsikan satu baris produk per order. Business key transaksi:
`(source, order_id, line_number=1)`; master: `sku`. Jika kelak satu order dapat memuat
beberapa baris, sumber perlu menyediakan line ID stabil. Baris konflik saat ini
dikarantina, bukan disimpulkan sebagai multi-item atau update terbaru tanpa bukti.
Duplikat nama vs SKU Website dikenali setelah product mapping.

Prioritas disposition: error/conflict → rejected; valid berulang → duplicates;
valid pertama → clean. Record invalid yang berulang tetap dihitung invalid.
Setiap record memiliki tepat satu disposition:

`extracted_records = valid_records + duplicate_records + invalid_records`

Satu record dapat melanggar lebih dari satu aturan; jumlah issues dan warning bukan
jumlah record ditolak. `valid_records` juga mencakup cancelled/returned dan record
dengan warning. Untuk revenue penjualan selesai, filter `status == 'COMPLETED'`;
gross amount tidak otomatis menjadi net revenue setelah refund/diskon.

## Menjalankan

Pilih kernel `env`, lalu Run All pada `analisis/analisa.ipynb` untuk overview;
notebook product/shopee/tokopedia/websit/offline menyediakan detail per sumber.
Semua notebook memakai enam pemeriksaan dan hasil akhir dengan urutan yang sama.
Validasi dihitung saat persiapan; tiap bagian menampilkan hasil pemeriksaannya.

```powershell
.\env\Scripts\python.exe -m pipeline.validation.analysis
.\env\Scripts\python.exe -m pytest tests/test_data_quality.py tests/test_analysis_format.py -q
```

Output utama `data/processed/clean/`: `product.csv`, `shopee.csv`, `tokopedia.csv`,
`website.csv`, `offline.csv`, `sales.csv` (gabungan), `summary.csv`, dan
`quality_issues.csv` (satu file detail masalah). Notebook per sumber hanya menulis
CSV sumber tersebut; jalankan `analisa.ipynb` atau CLI di atas untuk laporan gabungan.
Nomor record (mulai 1, tidak termasuk header), nama file, SHA-256, alasan masalah,
dan raw payload record ditolak/duplikat tersedia di laporan detail.
Metadata teknis tidak menambah kolom tabel transaksi yang ditampilkan.
Output merupakan snapshot terbaru. Folder hasil detail versi sebelumnya
`data/processed/data_quality/` tetap ada, tetapi bukan output utama notebook sekarang.

Validasi file menjadi input untuk pipeline database melalui staging, dimension,
dan fact loader. Record rejected tetap berada di laporan evidence file dan dapat
diteruskan ke tabel audit saat orkestrasi database diaktifkan. Pipeline database
memerlukan PostgreSQL yang sehat sebelum `pipeline.runner` dijalankan.

## Hasil snapshot sumber saat implementasi

| Sumber | Input | Clean | Duplicate | Rejected |
| --- | ---: | ---: | ---: | ---: |
| Product | 20 | 20 | 0 | 0 |
| Shopee | 618 | 595 | 18 | 5 |
| Tokopedia | 400 | 334 | 1 | 65 |
| Website | 412 | 395 | 12 | 5 |
| Offline | 360 | 345 | 10 | 5 |
| Total | 1810 | 1709 | 41 | 80 |

Tokopedia: 45 kejadian unmapped product, 9 invalid date, 13 non-positive numeric;
sebagian terjadi pada record sama sehingga rejected berjumlah 65. Sebanyak 165
perbedaan harga master diberi warning dan memerlukan tinjauan bisnis. Nilai
terbaru selalu dibaca dari `clean/summary.csv` dan `clean/quality_issues.csv`, bukan tabel snapshot ini.

## Kebijakan incremental loading

Business key warehouse adalah `(source_name, source_order_id, source_line_number)`.
Transform menghitung `source_record_hash` dari isi canonical row tanpa metadata
file. Transaksi baru di-insert; key sama dengan hash berbeda di-upsert; key dan
hash sama dilewati sebagai idempotent. Koreksi harga, status, kuantitas, tanggal,
atau SKU mengikuti aturan upsert ini.

Transaksi yang hilang dari snapshot tidak dihapus otomatis. Fact tetap aktif untuk
audit dan penghapusan hanya dilakukan melalui tombstone/reconciliation eksplisit.
Late-arriving transaction tetap diterima berdasarkan business key dan tanggalnya
diisi ke `dim_date`.

## Audit metrics

`audit.pipeline_runs` membedakan tahapan pipeline melalui
`extracted_records`, `validated_records`, `rejected_records`, `duplicate_records`,
`incremental_records`, `staged_records`, `dimension_records`,
`fact_inserted_records`, dan `fact_skipped_records`. Kolom lama `valid_records`,
`invalid_records`, dan `loaded_records` dipertahankan sebagai alias kompatibilitas;
metric baru menjadi sumber kebenaran operasional.

## Observability

`audit.pipeline_stage_runs` menyimpan status, durasi, dan jumlah record untuk
setiap tahap (`extract`, `validate`, `incremental_filter`, `transform`, `raw_load`,
`staging_load`, `dimension_load`, dan `fact_load`). `audit.source_ingestions`
menyimpan checksum SHA-256 dan waktu ingestion per source. Script
`scripts/check_freshness.py` memeriksa umur source file, sedangkan
`ALERT_WEBHOOK_URL` dapat digunakan untuk notifikasi failure.

Endpoint dashboard menggabungkan `pipeline_success_rate`, durasi run terakhir,
rejected/duplicate rate, fact load rate, source freshness, dan status stage terakhir
agar operasional dapat dipantau tanpa membaca log mentah.
