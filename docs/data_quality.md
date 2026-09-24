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
