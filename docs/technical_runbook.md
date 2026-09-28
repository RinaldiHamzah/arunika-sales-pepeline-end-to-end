# Runbook Operasional

## Tujuan

Dokumen ini menjadi panduan untuk menjalankan dan memantau pipeline, serta menangani kegagalan. Semua waktu menggunakan WIB (`Asia/Jakarta`).

Panduan ini ditujukan bagi operator dan developer. Jika layanan belum aktif, mulai dari bagian Menyalakan service.

## Menyalakan service

Jalankan `docker compose up -d --build`, kemudian pastikan layanan aktif dengan `docker compose ps`.

Service yang diharapkan sehat adalah `postgres`, `dashboard`, `airflow-dag-processor`, `airflow-scheduler`, dan `airflow-webserver`. `pipeline`, `airflow-init`, dan `airflow-db-bootstrap` dapat berstatus `Exited 0` karena memang berjalan satu kali.

## Menjalankan dan memeriksa pipeline

```powershell
.\env\Scripts\python.exe -m pipeline.runner
.\env\Scripts\python.exe .\scripts\check_warehouse.py
.\env\Scripts\python.exe .\scripts\check_freshness.py
.\env\Scripts\python.exe .\scripts\monitor_pipeline.py
```

Tambahkan opsi `--follow 10` pada `monitor_pipeline.py` untuk melihat pembaruan status setiap 10 detik.

## Membaca hasil run

Tabel utama adalah `audit.pipeline_runs`.

| Metrik | Arti |
| --- | --- |
| `source_records` | Seluruh baris transaksi pada snapshot source. |
| `skipped_unchanged_records` | Baris identik yang dilewati sebelum validasi. |
| `extracted_records` | Kandidat baru atau berubah yang masuk validasi. |
| `validated_records` | Kandidat yang lolos validasi. |
| `rejected_records` | Kandidat yang ditolak oleh rule kualitas data. |
| `duplicate_records` | Duplikat dalam kandidat validasi. |
| `incremental_records` | Kandidat yang siap masuk warehouse. |
| `fact_skipped_records` | Kandidat valid yang sama dengan fact warehouse. |
| `loaded_records` | Fact yang ditulis, termasuk insert atau koreksi. |

Jika status run `SUCCESS` dan `extracted_records = 0`, tidak ada data baru atau perubahan pada sumber. Ini hasil normal; data lama tidak diproses ulang.

Pada kondisi tersebut, runner berhenti setelah membandingkan snapshot. Tahap staging dan warehouse dilewati. Audit tetap mencatat status `SUCCESS`, jumlah baris yang dilewati, dan alasan data tidak diproses kembali.

Lihat tahap detail pada `audit.pipeline_stage_runs`. Log lokal berada di `logs/pipeline.log` dan `logs/dashboard.log`.

### Memantau run dari Dashboard

Saat pengguna menekan **Jalankan**, API mengembalikan `run_id` untuk eksekusi tersebut. Dashboard memeriksa `/api/pipeline/progress?run_id=<UUID>` kira-kira setiap satu detik dan berhenti saat run itu berstatus `SUCCESS` atau `FAILED`. Karena dashboard mengikuti ID yang tepat, status run lama tidak membuat indikator tetap menunggu. Status audit disimpan sebelum email laporan dikirim; indikator karena itu mengikuti penyelesaian pipeline, bukan waktu tibanya email.

Jika dashboard masih menampilkan status berjalan setelah riwayat menunjukkan run selesai, muat ulang halaman dengan `Ctrl+F5`. Pastikan juga backend dashboard memakai versi endpoint progress yang menerima parameter `run_id`.

## Jika pipeline gagal

1. Periksa `error_message` pada `audit.pipeline_runs`.
2. Periksa tahap yang gagal pada `audit.pipeline_stage_runs`.
3. Periksa `logs/pipeline.log`.
4. Perbaiki source, konfigurasi, atau service yang gagal.
5. Jalankan kembali pipeline. Mekanisme incremental dan idempotensi mencegah data yang sama dimuat berulang.

Jangan menghapus fact atau volume PostgreSQL sebagai langkah awal pemulihan.

## Airflow

DAG `ecommerce_sales_pipeline` didefinisikan di `airflow/orchestration.py` dan dijadwalkan setiap hari pukul 13.00 WIB. Jadwal dan status aktif DAG diatur melalui Airflow.

Jika file DAG atau Docker Compose berubah, jalankan `docker compose up -d --force-recreate airflow-dag-processor airflow-scheduler airflow-webserver`.

Periksa Airflow di `http://127.0.0.1:8080` dan health endpoint di `http://127.0.0.1:8080/api/v2/monitor/health`.

## Email dan alert

Laporan email menggunakan pengaturan SMTP di `.env`. Jika Gmail menolak koneksi dengan kode `534 5.7.9`, buat App Password baru dan masukkan nilainya ke `SMTP_PASSWORD`. Kegagalan email tidak membatalkan pipeline; detailnya dicatat dengan pesan `pipeline_email_failed` di log.

Laporan sukses merangkum hasil run yang bersangkutan. Jika ada data baru atau perubahan, laporan memuat jumlah transaksi yang masuk ke Raw Layer, hasil pemeriksaan kualitas, jumlah data yang lolos ke staging, dan fact yang ditulis. Jika sumber tidak berubah, metrik pemrosesan bernilai `0`. Hasil pemeriksaan kualitas dari run lama tidak disalin ke laporan baru.

`ALERT_WEBHOOK_URL` bersifat opsional untuk notifikasi kegagalan melalui webhook.

## Migration dan deployment

Sebelum memakai kode baru pada database yang sudah ada, jalankan `.\env\Scripts\python.exe -m alembic upgrade head`.

Mulai ulang backend lokal setelah mengubah kode Python. Di Docker, build ulang service yang menjalankan kode pipeline; kode pipeline disalin ke image. Template dan aset di `dashboard/` dipasang sebagai volume, tetapi perubahan pada `dashboard/app.py` atau `dashboard/routes.py` tetap memerlukan restart service Dashboard. Jangan commit `.env`, log, atau kredensial.

### Integration test tidak menemukan revision Alembic

Jika integration test menampilkan pesan seperti `Can't locate revision identified by '20260928_11'`, database test masih menyimpan revision lama yang sudah tidak ada di source code. Bersihkan hanya container dan volume sementara milik profile test, lalu jalankan ulang test:

```powershell
docker compose --profile test rm -sfv postgres-test integration-tests
.\env\Scripts\python.exe .\tests\main.py --full
```

Perintah tersebut hanya menghapus state test terisolasi. Jangan gunakan perintah ini pada service `postgres` utama karena service tersebut menyimpan warehouse development.
