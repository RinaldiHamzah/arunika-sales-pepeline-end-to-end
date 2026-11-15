# Dokumentasi Dashboard

Dashboard Arunika adalah antarmuka untuk membaca hasil penjualan dan menjalankan operasi pipeline tertentu. Aplikasi ini memakai Flask, HTML, CSS biasa, JavaScript ES module, dan Chart.js lokal. Tidak ada framework frontend tambahan atau proses build terpisah.

Dashboard dirender sebagai satu halaman dengan beberapa tampilan. Hash URL dan JavaScript hanya mengatur bagian yang sedang terlihat, sehingga filter dan state tetap dapat dipakai lintas tampilan.

## Tampilan yang tersedia

| Tampilan | Isi |
| --- | --- |
| **Ringkasan** | KPI, filter periode, tren penjualan, dan tab analitik. |
| **Tab Penjualan** | Kontribusi kanal, status pesanan, dan kota teratas. |
| **Tab Produk** | Merek, kategori, SKU, dan produk terlaris. |
| **Transaksi** | Rincian transaksi sesuai filter, pagination, dan unduh CSV. |
| **Pengaturan** | Status pipeline, upload CSV, menjalankan pipeline, dan riwayat eksekusi. |

Pengaturan memakai `DASHBOARD_ADMIN_TOKEN` untuk upload, menjalankan pipeline, dan membaca informasi operasional yang dilindungi.

Contoh tampilan tersedia pada [Dashboard Ringkasan](../docs/images/dashboard.png), [Rincian Transaksi](../docs/images/transaksi.png), dan [Pengaturan Pipeline](../docs/images/pengaturan.png).

## Cara menggunakan

### Ringkasan dan analitik

1. Pilih rentang tanggal cepat atau tanggal mulai dan selesai.
2. Pilih filter kanal, status, kategori, merek, atau produk jika diperlukan.
3. Klik **Apply** untuk memuat hasil.
4. Gunakan tab **Penjualan** dan **Produk** untuk melihat rincian analitik.

### Transaksi

Transaksi mengikuti filter terakhir yang diterapkan pada Ringkasan. Gunakan pagination untuk berpindah halaman atau **Unduh CSV** untuk menyimpan hasil filter.

### Pengaturan dan token administrator

1. Masukkan token pada area **Token Administrator**.
2. Pilih sumber data dan unggah CSV. Upload mendukung empat kanal, master produk, master promo, dan return/refund. Header diperiksa saat upload; validasi isi dilakukan pipeline otomatis setelah file tersimpan. Empat CSV kanal dapat memakai header lama atau header lengkap dengan `discount_amount` dan `promo_code`. Diskon harus sudah dicatat pada grain baris item; jika sumber memberi diskon per order, alokasikan dahulu ke item dengan jumlah alokasi yang sama persis dengan diskon order. Upload dashboard menambahkan batch ke CSV yang sudah ada.
3. Tunggu sampai status pipeline selesai sebelum mengunggah file berikutnya. Pesan selesai membedakan batch yang menghasilkan perubahan dari baris yang sudah pernah diproses dan dilewati. Jika halaman dimuat ulang saat run berjalan, masukkan token lalu klik **Check Status** untuk menyambung kembali ke pemantauan run aktif.
4. Tombol **Jalankan** tetap tersedia untuk menjalankan pipeline secara manual; **Check Status** memuat ulang riwayat pipeline.

Token hanya digunakan untuk request admin selama halaman aktif dan tidak disimpan ke `localStorage`.

CSV aktif tetap berada di `data/source` pada folder proyek. Untuk header lengkap, upload
menambahkan batch ke berkas yang sama tanpa mengganti berkas melalui rename, sehingga
sesuai dengan mount Windows yang mengizinkan penulisan tetapi menolak penggantian berkas.
Upload dan pipeline memakai kunci PostgreSQL yang sama; tunggu proses aktif selesai
sebelum mengunggah. Jika penulisan batch gagal, panjang berkas dikembalikan ke ukuran
sebelumnya. Penghentian paksa proses saat menulis tetap perlu pemeriksaan integritas CSV.
Peningkatan header lama menjadi header lengkap masih menggunakan penggantian berkas
dan memerlukan izin tersebut. Unggah hanya batch baru agar tidak menggandakan isi sumber.

## Status koneksi dan refresh

Di navbar, indikator titik menunjukkan status gudang:

- Hijau berarti terhubung.
- Kuning berarti sedang memuat atau memproses.
- Merah berarti koneksi perlu diperiksa.

Tombol **Refresh** memuat ulang data menggunakan filter terakhir yang sudah diterapkan. Refresh otomatis ditunda ketika pengguna sedang mengubah filter atau membaca tabel.

## Perilaku responsif dan aksesibilitas

- Pada layar kecil, panel filter dapat ditutup agar KPI lebih cepat terlihat.
- Tabel transaksi dan riwayat berubah menjadi kartu pada mobile.
- Tab analitik dapat dioperasikan dengan panah kiri/kanan, `Home`, dan `End`.
- Setiap grafik memiliki opsi untuk melihat data dalam bentuk tabel.
- Jika Chart.js gagal dimuat, tabel alternatif tetap tersedia.
- Kontrol memiliki focus state, label form, dan teks alternatif untuk pembaca layar.

## Struktur file

| File | Tanggung jawab |
| --- | --- |
| `app.py` | Entry point aplikasi, application factory, koneksi database, cache-busting aset, dan middleware logging. Docker menjalankan `dashboard.app:app`. |
| `routes.py` | Endpoint halaman, API dashboard, ekspor CSV, upload, dan operasi pipeline. |
| `services/analytics.py` | Query PostgreSQL untuk KPI, grafik, filter, transaksi, dan observability pipeline. |
| `services/formatting.py` | Konversi row database menjadi respons JSON yang aman dan konsisten. |
| `services/ingestion.py` | Validasi kontrak serta penambahan batch CSV dari halaman Pengaturan. |
| `templates/base.html` | Shell HTML, navbar, header, status koneksi, dan pesan. |
| `templates/dashboard.html` | Filter, KPI, tab analitik, dan Ringkasan. |
| `templates/transactions.html` | Tampilan Transaksi yang di-include oleh `dashboard.html`. |
| `templates/settings.html` | Pengaturan pipeline dan riwayat eksekusi. |
| `static/css/dashboard.css` | Entry point stylesheet. |
| `static/css/tokens.css` | Warna, tipografi, focus state, dan default dokumen. |
| `static/css/layout.css` | Navbar, header, grid, dan struktur halaman. |
| `static/css/components.css` | Form, KPI, tabel, tombol, dan panel operasi. |
| `static/css/charts.css` | Canvas dan tabel alternatif grafik. |
| `static/css/responsive.css` | Breakpoint mobile dan reduced motion. |
| `static/js/chart.umd.min.js` | Library Chart.js untuk visualisasi grafik. |
| `static/js/dashboard.js` | Bootstrap aplikasi. |
| `static/js/core.js` | State, format WIB, filter, dan helper DOM. |
| `static/js/api.js` | Request API, timeout, dan error. |
| `static/js/charts.js` | Pembuatan dan pembaruan Chart.js. |
| `static/js/renderers.js` | Render KPI, tabel, peringkat, dan riwayat. |
| `static/js/interactions.js` | Navigasi, filter, upload, polling, dan refresh. |

`dashboard.html` mewarisi `base.html`; `transactions.html` dan `settings.html` di-include dari template tersebut. Pertahankan ID kontrol ketika mengubah tampilan karena JavaScript mengambil elemen berdasarkan ID. Endpoint tetap berada di `routes.py`, sedangkan query dan operasi bisnis berada di `services/`; jangan memindahkan logika tersebut ke HTML atau menambahkan override layout acak ke `dashboard.css`.

## Pengujian tampilan

Jalankan dari root repository:

```powershell
node dashboard/tests/browser_smoke.mjs
```

Test membutuhkan Node.js 22+ serta Chrome atau Edge. Test memakai server sementara dan data simulasi; tidak membaca `.env`, tidak mengirim email, dan tidak menjalankan pipeline sungguhan. Test mencakup viewport 320 sampai 1440 piksel, navigasi, keyboard, kartu mobile, filter, pagination, upload, polling, pemulihan API, dan fallback grafik.
# Upload tambah dan koreksi

Pada Pengaturan, pilih sumber dan file CSV lalu klik **Upload CSV**. UI menambahkan data ke sumber, kemudian otomatis menjalankan pipeline dan memantau run tersebut. Keberhasilan upload berarti data tersimpan, bukan jaminan bahwa baris baru masuk Raw, Staging, atau Warehouse: baris yang identik dengan data yang sudah tercatat akan dilewati incremental loading dan status UI menjelaskannya. Mode koreksi eksplisit tetap tersedia pada API untuk kompatibilitas, tetapi tidak ditampilkan sebagai pilihan di UI. Koreksi API mengganti baris dengan key yang sudah ada; key baru atau beberapa versi berbeda untuk key yang sama dalam batch koreksi ditolak.

Key kanal adalah ID order + nomor baris (kanal ditentukan dari pilihan sumber); master produk menggunakan SKU; master promo menggunakan kode promo; return menggunakan kanal + ID return + nomor baris return. Jangan mengubah key untuk mengoreksi nilai transaksi.

Promo dan return identik diproses sekali. Konflik promo tetap menggagalkan validasi, bukan memilih baris terakhir secara diam-diam; konflik return dicatat sebagai penolakan. Payload promo sekarang disimpan ke Raw sebelum validasi bisnis, termasuk pada run gagal. Gunakan koreksi eksplisit untuk menyelesaikan konflik.

Koreksi memakai penggantian file atomik di bawah kunci pipeline. Jika Windows/OneDrive menolak penggantian, upload gagal dan file asli tidak berubah; jangan menganggap koreksi berhasil. Beri izin penggantian berkas pada folder proyek atau selesaikan penguncian file terlebih dahulu. Sumber tetap berada di folder proyek, bukan dipindahkan ke volume Docker.
