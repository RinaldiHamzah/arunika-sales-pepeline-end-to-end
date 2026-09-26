# Kebijakan Kualitas Data

Aturan `pipeline.validation` digunakan bersama oleh notebook analisis, export clean CSV, dan pipeline database.

Tujuan kebijakan ini adalah menjaga agar angka di dashboard dapat ditelusuri kembali ke data sumber. Record yang tidak memenuhi aturan tidak diperbaiki dengan tebakan; record tersebut ditolak atau diberi peringatan sesuai jenis masalahnya.

## Kontrak data bersih

Transaksi memakai kolom berikut:

```text
order_id,product_id,product_name,kategori,quantity,total_harga,tanggal_order,kota,channel,status,customer_email,harga_satuan
```

Grain transaksi adalah satu baris per order. Business key internal adalah `(source, order_id, line_number)`. `line_number` saat ini bernilai `1` karena source belum menyediakan line ID stabil. `customer_id` tidak masuk ke clean contract karena tidak tersedia pada semua source.

Product Master memakai:

```text
product_id,product_name,brand,kategori,harga_satuan
```

`product_id` adalah SKU dari Product Master. Nama, brand, dan kategori produk mengikuti master yang sudah valid.

## Aturan dan perlakuan

| Pemeriksaan | Aturan | Perlakuan |
| --- | --- | --- |
| Missing value | Nilai kosong, whitespace, `NA`, dan `NULL` dianggap kosong. | Field wajib ditolak; field opsional tetap `null` dengan warning. |
| Field wajib | Order ID, tanggal, produk, quantity, harga satuan, dan status wajib ada. | Tidak diisi dengan tebakan. |
| Duplikat sama | Business key dan nilai canonical sama. | Satu record disimpan, sisanya dicatat sebagai duplicate. |
| Duplikat konflik | Business key sama tetapi isi berbeda. | Semua versi dikarantina sebagai rejected. |
| Quantity | Bilangan bulat positif dalam batas `INTEGER`. | Nol, negatif, pecahan, atau nonnumerik ditolak. |
| Harga dan total | Nilai uang positif, maksimal dua desimal. | Nilai tidak valid ditolak. |
| Total Website | `total_amount` harus sama dengan `quantity × unit_price`. | Missing atau mismatch ditolak. |
| Status | Hanya `COMPLETED`, `CANCELLED`, `RETURNED`. | Status lain ditolak. |
| Tanggal | Format source diparse eksplisit lalu menjadi `YYYY-MM-DD`. | Tanggal mustahil atau format tidak dikenal ditolak. |
| Produk | SKU atau nama dinormalisasi lalu dicocokkan ke master. | Produk tidak ditemukan ditolak sebagai `UNMAPPED_PRODUCT`. |
| Harga berbeda master | Harga transaksi positif tetapi berbeda dari referensi. | Harga source dipertahankan dan diberi warning. |
| Email | Bila tersedia, struktur email diperiksa. | Email tidak valid menjadi `null` dengan warning. |

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

Satu record dapat melanggar beberapa rule sehingga jumlah issue tidak selalu sama dengan jumlah record rejected.

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

Output utama ada di `data/processed/clean/`: `product.csv`, `shopee.csv`, `tokopedia.csv`, `website.csv`, `offline.csv`, `sales.csv`, `summary.csv`, dan `quality_issues.csv`.

```powershell
.\env\Scripts\python.exe -m pipeline.validation.analysis
.\env\Scripts\python.exe -m pytest tests/test_data_quality.py tests/test_analysis_format.py -q
```

Record rejected dan duplicate menyimpan nomor baris, nama file, checksum, alasan, dan payload mentah sebagai evidence audit.

## Laporan hasil quality check

Laporan quality tersimpan di PostgreSQL untuk setiap `run_id`. Dengan demikian hasilnya tidak bergantung pada tampilan dashboard atau file CSV sementara. Ada dua tingkat laporan:

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
.\env\Scripts\ython.exe .\scripts\report_data_quality.py --run-id <UUID_RUN>
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
       invalid_price_or_amount_recordps,
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
