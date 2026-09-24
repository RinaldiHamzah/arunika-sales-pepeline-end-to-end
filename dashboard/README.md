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

## Cara menggunakan

### Ringkasan dan analitik

1. Pilih rentang tanggal cepat atau tanggal mulai dan selesai.
2. Pilih filter kanal, status, kategori, merek, atau produk jika diperlukan.
3. Klik **Terapkan** untuk memuat hasil.
4. Gunakan tab **Penjualan** dan **Produk** untuk melihat rincian analitik.

### Transaksi

Transaksi mengikuti filter terakhir yang diterapkan pada Ringkasan. Gunakan pagination untuk berpindah halaman atau **Unduh CSV** untuk menyimpan hasil filter.

### Pengaturan dan token administrator

1. Masukkan token pada area **Token Administrator**.
2. Pilih sumber data dan unggah CSV pada Langkah 1.
3. Jalankan pipeline pada Langkah 2.
4. Klik **Check Status** untuk memuat riwayat pipeline.

Token hanya digunakan untuk request admin selama halaman aktif dan tidak disimpan ke `localStorage`.

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
| `templates/base.html` | Shell HTML, navbar, header, status koneksi, dan pesan. |
| `templates/dashboard.html` | Filter, KPI, tab analitik, dan Ringkasan. |
| `templates/transactions.html` | Tampilan Transaksi yang di-include oleh `dashboard.html`. |
| `templates/settings.html` | Pengaturan pipeline dan riwayat eksekusi. |
| `static/dashboard.css` | Entry point stylesheet. |
| `static/tokens.css` | Warna, tipografi, focus state, dan default dokumen. |
| `static/layout.css` | Navbar, header, grid, dan struktur halaman. |
| `static/components.css` | Form, KPI, tabel, tombol, dan panel operasi. |
| `static/charts.css` | Canvas dan tabel alternatif grafik. |
| `static/responsive.css` | Breakpoint mobile dan reduced motion. |
| `static/dashboard.js` | Bootstrap aplikasi. |
| `static/core.js` | State, format WIB, filter, dan helper DOM. |
| `static/api.js` | Request API, timeout, dan error. |
| `static/charts.js` | Pembuatan dan pembaruan Chart.js. |
| `static/renderers.js` | Render KPI, tabel, peringkat, dan riwayat. |
| `static/interactions.js` | Navigasi, filter, upload, polling, dan refresh. |

`dashboard.html` mewarisi `base.html`; `transactions.html` dan `settings.html` di-include dari template tersebut. Pertahankan ID kontrol ketika mengubah tampilan karena JavaScript mengambil elemen berdasarkan ID. Jangan memindahkan logika API ke HTML atau menambahkan override layout acak ke `dashboard.css`.

## Pengujian tampilan

Jalankan dari root repository:

```powershell
node dashboard/tests/browser_smoke.mjs
```

Test membutuhkan Node.js 22+ serta Chrome atau Edge. Test memakai server sementara dan data simulasi; tidak membaca `.env`, tidak mengirim email, dan tidak menjalankan pipeline sungguhan. Test mencakup viewport 320 sampai 1440 piksel, navigasi, keyboard, kartu mobile, filter, pagination, upload, polling, pemulihan API, dan fallback grafik.
