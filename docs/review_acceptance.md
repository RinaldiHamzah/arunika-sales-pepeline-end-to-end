# Bukti pemeriksaan sebelum review

Tanggal pemeriksaan: 12 November 2026. Hasil ini berlaku pada kode yang diuji, bukan jaminan bebas bug untuk seluruh kemungkinan data atau lingkungan.

## Hasil verifikasi

| Pemeriksaan | Hasil |
| --- | --- |
| Tes non-integrasi | 161 lulus, 1 tes integrasi dikecualikan |
| Tes PostgreSQL terisolasi | 1 skenario end-to-end lulus |
| Browser smoke | Lulus, 6 ukuran layar × 6 tampilan serta upload, run, refresh, pagination, dan pemulihan API |
| Koreksi lewat endpoint untuk 8 sumber pada file sementara di mount Windows | Seluruhnya HTTP 201 |
| Dashboard health dan API data | HTTP 200 |
| Airflow metadatabase, scheduler, dan DAG processor | Healthy |
| Pemeriksaan Ruff pada file Python yang diubah | Lulus |

Tes integrasi meliputi multi-item, incremental/no-op, koreksi, rekonsiliasi snapshot dan reaktivasi, serta perbandingan KPI API dengan SQL warehouse. Tambahan skenario mengunggah ulang master promo, order promotion, dan return melalui endpoint HTTP lalu menjalankan ETL; KPI tetap sama. Koreksi order promotion melalui endpoint kemudian mengubah total diskon order di warehouse menjadi nominal yang diuji, tanpa menggandakan key.

## Kontrak operasional

Detail Proses sekarang memiliki bagian Sumber Tambahan untuk Master Promo, Order Promotion, dan Return. Metrik tersimpan di `report_summary.auxiliary_sources` untuk run baru, termasuk no-op. Promo melaporkan validasi seluruh file (valid unik, duplikat identik, perubahan file, dan jumlah Raw); return melaporkan delta, baris tidak berubah, valid unik, duplikat, ditolak, dan event ditulis. Order Promotion tidak memiliki jumlah pemuatan warehouse mandiri karena diterapkan melalui fact penjualan. Riwayat tanpa metrik tersebut menampilkan “Belum tercatat”, bukan angka nol rekaan.

Pengujian juga menemukan dan memperbaiki alokasi diskon order pada transaksi sumber identik yang diunggah berulang. Basis alokasi sekarang per baris order unik, sementara salinan identik dipertahankan untuk audit kualitas. Konflik isi pada baris order yang menggunakan promo ditolak agar nominal tidak dialokasikan secara ambigu.

- Kanal penjualan memakai key `(source_name, source_order_id, source_line_number)`; nomor baris harus stabil.
- UI menyediakan satu alur upload yang menambahkan data sumber, kemudian pengguna menjalankan validasi pipeline. Pilihan mode koreksi telah dihapus dari UI atas permintaan pengguna. Kemampuan koreksi eksplisit pada API tetap tersedia untuk kompatibilitas; pengujian koreksi di atas mengacu pada API tersebut.
- Duplikat identik master promo, order promotion, dan return diproses sekali. Konflik isi tidak diselesaikan dengan mengambil baris terakhir: konflik promo menghentikan validasi; konflik return masuk audit penolakan.
- Raw promo disimpan sebelum validasi bisnis agar run gagal masih memiliki bukti sumber. Promo/return tidak memiliki tabel staging terpisah; normalisasi dilakukan di Python, sedangkan diskon order diteruskan melalui staging penjualan.
- Rekonsiliasi penghilangan hanya berlaku untuk deklarasi FULL_SNAPSHOT lengkap dengan cakupan ALL_HISTORY. Batch tambahan tidak boleh dipakai menyimpulkan transaksi dihapus.
- Gross eligible mengecualikan CANCELLED. Net eligible adalah gross dikurangi diskon dan refund PROCESSED. Unit return rate memakai jumlah unit APPROVED/PROCESSED dibagi unit penjualan eligible.
- Overview memakai tanggal order; analisis operasional return memakai tanggal return. Perbandingan kedua nominal harus memperhatikan dasar tanggal dan filter.

## Batas bukti

Tidak ada CSV asli yang diubah untuk pengujian; perubahan pengguna pada `returns.csv` dipertahankan. Pengujian ETL dilakukan pada database terisolasi, bukan menjalankan ulang pipeline produksi atau mengirim email laporan. Koreksi atomik berhasil pada file sementara di mount yang sama; file asli yang dikunci aplikasi atau memiliki ACL berbeda masih dapat ditolak Windows. Pada kegagalan penggantian atomik, file asli tidak diubah.

Sebelum demonstrasi, muat ulang browser dengan Ctrl+Shift+R, pilih sumber dan file CSV, tunggu konfirmasi upload, lalu jalankan pipeline. Periksa status run dan alasan penolakan; HTTP 201 upload hanya membuktikan penyimpanan sumber, bukan kelulusan validasi bisnis.

## Mengulang pengujian

```powershell
python -m pytest tests -q -m "not integration"
docker compose --profile test up --build --abort-on-container-exit --exit-code-from integration-tests integration-tests
node dashboard/tests/browser_smoke.mjs
```

Profil integrasi menggunakan database test khusus; jangan mengarahkan tes tersebut ke database produksi.
