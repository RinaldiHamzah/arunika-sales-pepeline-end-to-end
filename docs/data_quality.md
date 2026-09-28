# Kebijakan Kualitas Data

Notebook analisis, ekspor CSV bersih, dan pipeline database menggunakan aturan validasi yang sama dari `pipeline.validation`.

Kebijakan ini menjaga agar angka di dashboard dapat ditelusuri kembali ke sumber data. Baris yang bermasalah tidak diperbaiki dengan perkiraan; sistem menolaknya atau mencatat peringatan sesuai jenis masalah.

## Kontrak data bersih

Transaksi memakai kolom berikut:

```text
order_id,product_id,product_name,kategori,quantity,total_harga,tanggal_order,kota,channel,status,customer_email,harga_satuan
```

Setiap baris pada data transaksi bersih mewakili satu order. Business key internalnya adalah `(source, order_id, line_number)`. Nilai `line_number` saat ini `1` karena sumber belum menyediakan ID baris yang konsisten. `customer_id` tidak disertakan karena tidak tersedia di semua sumber.

Product Master memakai:

```text
product_id,product_name,brand,kategori,harga_satuan
```

`product_id` adalah SKU dari Product Master. Nama, merek, dan kategori produk mengikuti data master yang lolos validasi.

## Aturan dan perlakuan

| Pemeriksaan | Aturan | Perlakuan |
| --- | --- | --- |
| Nilai kosong | Nilai kosong, spasi, `NA`, dan `NULL` dianggap sebagai data kosong. | Baris dengan kolom wajib kosong ditolak. Kolom opsional tetap `null` dan diberi peringatan. |
| Field wajib | Order ID, tanggal, produk, quantity, harga satuan, dan status wajib ada. | Tidak diisi dengan tebakan. |
| Duplikat sama | Business key dan nilai standar sama. | Satu baris dipertahankan; sisanya dicatat sebagai duplikat. |
| Duplikat konflik | Business key sama, tetapi isi berbeda. | Semua versi ditolak agar sistem tidak memilih data secara sembarang. |
| Quantity | Bilangan bulat positif dalam batas `INTEGER`. | Nol, negatif, pecahan, atau nonnumerik ditolak. |
| Harga dan total | Nilai uang positif, maksimal dua desimal. | Nilai tidak valid ditolak. |
| Total Website | `total_amount` harus sama dengan `quantity × unit_price`. | Missing atau mismatch ditolak. |
| Status | Hanya `COMPLETED`, `CANCELLED`, `RETURNED`. | Status lain ditolak. |
| Tanggal | Format setiap sumber dibaca sesuai aturan lalu diubah ke `YYYY-MM-DD`. | Tanggal yang tidak mungkin atau format yang tidak dikenali ditolak. |
| Produk | SKU atau nama dinormalisasi dan dicocokkan dengan master. | Produk yang tidak ditemukan ditolak dengan alasan `UNMAPPED_PRODUCT`. |
| Harga berbeda dari master | Harga transaksi valid, tetapi berbeda dari harga referensi. | Harga dari sumber dipertahankan dan perbedaannya dicatat sebagai peringatan. |
| Email | Format email diperiksa jika nilainya tersedia. | Email tidak valid diubah menjadi `null` dan diberi peringatan. |

## Normalisasi

- Teks memakai Unicode NFKC dan whitespace dinormalisasi.
- Nama kolom hasil memakai `snake_case`.
- SKU master dan status internal memakai huruf besar.
- Nama produk memakai kapitalisasi Product Master; pipeline tidak memakai `.title()`.
- Identifier disimpan sebagai string agar leading zero tidak hilang.
- Quantity memakai integer nullable, tanggal memakai datetime, dan uang memakai `Decimal`.
- Kota kosong tidak ditebak. Kota hanya diperkaya dari customer natural key yang sama dan sudah terverifikasi.

## Disposisi record

```text
error atau konflik  → rejected
valid dan berulang  → duplicate
valid pertama       → clean
```

Satu baris dapat melanggar beberapa aturan. Karena itu, jumlah temuan tidak selalu sama dengan jumlah baris yang ditolak.

```text
extracted_records = valid_records + duplicate_records + invalid_records
```

`valid_records` dapat mencakup transaksi `CANCELLED` dan `RETURNED`. Analisis revenue perlu memfilter status sesuai definisi bisnis, umumnya `COMPLETED`.

## Incremental loading

Warehouse memakai business key `(source_name, source_order_id, source_line_number)` dan `source_record_hash`.

- Key baru akan di-insert.
- Key sama dengan hash berbeda diproses sebagai koreksi atau upsert.
- Key dan hash sama dilewati.
- Transaksi yang hilang dari source tidak dihapus otomatis.
- Transaksi yang datang terlambat tetap diterima menggunakan tanggal transaksinya.

## Output dan perintah

Output utama ada di `data/processed/`: `product.csv`, `shopee.csv`, `tokopedia.csv`, `website.csv`, `offline.csv`, `sales.csv`, `summary.csv`, dan `quality_issues.csv`.

```powershell
.\env\Scripts\python.exe -m pipeline.validation.analysis
.\env\Scripts\python.exe -m pytest tests/test_data_quality.py tests/test_analysis_format.py -q
```

Baris yang ditolak atau terdeteksi sebagai duplikat menyimpan nomor baris, nama file, checksum, alasan, dan payload asli sebagai bukti audit.

## Laporan hasil quality check

Hasil pemeriksaan kualitas disimpan di PostgreSQL untuk setiap `run_id`, sehingga tetap tersedia meskipun tampilan dashboard atau file CSV berubah. Laporan disajikan dalam dua tingkat:

| Tingkat | Sumber | Isi |
| --- | --- | --- |
| Ringkasan per source | `audit.v_data_quality_report` | Total source, kandidat baru/berubah, data identik yang dilewati, valid akhir, rejected, duplicate, missing, invalid quantity, invalid price/amount, invalid date, invalid status, produk tidak termapping, issue lain, dan warning. |
| Bukti per rule dan field | `audit.v_data_quality_by_rule` | Source, nama rule, severity, jumlah temuan, nama kolom, dan kategori temuan. |

Angka `valid_records`, `rejected_records`, dan `duplicate_records` adalah jumlah record. Kolom berakhiran `*_records` pada kategori issue adalah jumlah temuan rule, bukan selalu jumlah record unik: satu baris yang memiliki harga dan tanggal tidak valid memang dihitung pada dua kategori agar penyebabnya terlihat lengkap.

Jalankan laporan untuk run terbaru:

```powershell
.\env\Scripts\python.exe .\scripts\report_data_quality.py
```

Atau pilih run tertentu:

```powershell
.\env\Scripts\python.exe .\scripts\report_data_quality.py --run-id <UUID_RUN>
```

Contoh SQL untuk reviewer:

```sql
SELECT source_name,
       source_records,
       candidate_records,
       skipped_unchanged_records,
       valid_records,
       rejected_records,
       duplicate_records,
       missing_value_records,
       invalid_quantity_records,
       invalid_price_or_amount_records,
       invalid_date_records,
       invalid_status_records,
       unmapped_product_records,
       warning_issue_records
FROM audit.v_data_quality_report
WHERE run_id = '<UUID_RUN>'
ORDER BY source_name;
```

Untuk melihat penyebab sampai level kolom:

```sql
SELECT source_name,
       rule_name,
       severity,
       details ->> 'field' AS field_name,
       details ->> 'category' AS category,
       failed_records
FROM audit.v_data_quality_by_rule
WHERE run_id = '<UUID_RUN>'
ORDER BY source_name, severity DESC, rule_name, field_name;
```

Kategori laporan memiliki arti berikut:

| Kategori | Rule/field yang masuk |
| --- | --- |
| `missing_value_records` | `MISSING_REQUIRED` atau `MISSING_OPTIONAL`. |
| `duplicate_issue_records` | `DUPLICATE_BUSINESS_KEY` atau `CONFLICTING_DUPLICATE`. |
| `invalid_quantity_records` | Kesalahan angka pada kolom `qty`, `quantity`, atau `units`. |
| `invalid_price_or_amount_records` | Kesalahan angka/mismatch pada `price`, `unit_price`, `item_price`, atau `total_amount`; termasuk perbedaan harga terhadap master sebagai warning. |
| `invalid_date_records` | `INVALID_DATE`. |
| `invalid_status_records` | `INVALID_STATUS`. |
| `unmapped_product_records` | `UNMAPPED_PRODUCT`. |
| `other_issue_records` | Misalnya email atau metode pembayaran tidak valid yang tidak termasuk kategori di atas. |

Run lama tetap dapat dilihat, tetapi detail kategori field mulai tersedia untuk run yang dibuat setelah migration ini aktif. Rule yang dapat muncul mencakup `MISSING_REQUIRED`, `MISSING_OPTIONAL`, `DUPLICATE_BUSINESS_KEY`, `CONFLICTING_DUPLICATE`, `INVALID_NUMBER`, `INVALID_INTEGER`, `INVALID_MONEY_PRECISION_OR_RANGE`, `INVALID_STATUS`, `INVALID_DATE`, `AMOUNT_MISMATCH`, `UNMAPPED_PRODUCT`, dan `INVALID_EMAIL`.
