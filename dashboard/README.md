# Dokumentasi Dashboard

Dashboard memakai Flask, CSS biasa, JavaScript ES module, dan Chart.js lokal. Tidak ada framework frontend tambahan atau proses build terpisah.

## Halaman utama

| Halaman | Fungsi |
| --- | --- |
| **Overview** | KPI, tren penjualan, channel, dan status transaksi. |
| **Penjualan** | Kontribusi channel, status order, dan kota. |
| **Produk** | Brand, kategori, SKU, dan produk terlaris. |
| **Operasional** | Kesehatan pipeline dan freshness source. |
| **Transactions** | Transaksi sesuai filter, pagination, dan unduh CSV. |
| **Settings** | Upload batch, menjalankan pipeline, dan riwayat eksekusi. |

Halaman **Settings** membutuhkan `DASHBOARD_ADMIN_TOKEN` untuk upload, menjalankan pipeline, dan melihat data operasional yang dilindungi.

## Penggunaan dasar

1. Pilih periode atau preset tanggal.
2. Tambahkan filter channel, status, kategori, brand, atau produk bila diperlukan.
3. Klik **Terapkan** untuk memuat data.
4. Gunakan **Transactions** untuk melihat detail dan mengunduh hasil filter.
5. Gunakan **Settings** untuk mengunggah CSV atau menjalankan pipeline.

## Perilaku responsif dan aksesibilitas

- Pada layar kecil, panel filter dapat ditutup agar KPI cepat terlihat.
- Tabel transaksi dan riwayat berubah menjadi kartu pada mobile.
- Tab analitik dapat dioperasikan dengan panah kiri/kanan, `Home`, dan `End`.
- Setiap grafik memiliki opsi **Lihat data tabel**.
- Bila Chart.js gagal dimuat, tabel alternatif tetap tersedia.
- Refresh otomatis memakai filter terakhir yang sudah diterapkan dan ditunda saat pengguna sedang mengubah filter atau membaca tabel.

## Struktur file

| File | Tanggung jawab |
| --- | --- |
| `templates/base.html` | Template utama: HTML shell, navigasi, header, pesan, dan block halaman. |
| `templates/dashboard.html` | Child template: filter dan halaman Overview. |
| `templates/transactions.html` | Halaman Transactions yang di-include oleh `dashboard.html`. |
| `templates/settings.html` | Halaman Settings yang di-include oleh `dashboard.html`. |
| `static/dashboard.css` | Entry point stylesheet. |
| `static/tokens.css` | Warna, tipografi, dan aksesibilitas. |
| `static/layout.css` | Shell, navigasi, dan layout. |
| `static/components.css` | Form, KPI, tabel, dan panel operasi. |
| `static/charts.css` | Canvas dan tabel alternatif grafik. |
| `static/responsive.css` | Breakpoint dan reduced motion. |
| `static/dashboard.js` | Bootstrap aplikasi. |
| `static/core.js` | State, format WIB, filter, dan helper DOM. |
| `static/api.js` | Request API, timeout, dan error. |
| `static/charts.js` | Pembuatan serta pembaruan Chart.js. |
| `static/renderers.js` | Render KPI, tabel, peringkat, dan riwayat. |
| `static/interactions.js` | Navigasi, filter, upload, polling, dan refresh. |

`dashboard.html` mewarisi `base.html`; Transactions dan Settings di-include dari child tersebut. Keempat template dirender sebagai satu halaman agar state JavaScript tetap sama. Pertahankan ID kontrol ketika mengubah template. Jangan memindahkan logika API ke HTML atau menambahkan override layout acak ke `dashboard.css`.

## Pengujian tampilan

Jalankan dari root repository:

```powershell
node dashboard/tests/browser_smoke.mjs
```

Test membutuhkan Node.js 22+ serta Chrome atau Edge. Test memakai server sementara dan data simulasi; tidak membaca `.env`, tidak mengirim email, dan tidak menjalankan pipeline sungguhan. Test mencakup viewport 320 sampai 1440 piksel, navigasi, keyboard, kartu mobile, filter, pagination, upload, polling, dan fallback grafik.
