# Runbook Operasional

## Tujuan

Gunakan dokumen ini untuk menjalankan, memantau, dan memulihkan pipeline secara aman. Semua waktu menggunakan WIB (`Asia/Jakarta`).

Runbook ditujukan untuk operator atau developer yang perlu menjalankan pipeline, membaca hasilnya, atau menangani kegagalan. Mulailah dari bagian Menyalakan service jika lingkungan belum berjalan.

## Menyalakan service

Jalankan `docker compose up -d --build`, lalu periksa dengan `docker compose ps`.

Service yang diharapkan sehat adalah `postgres`, `dashboard`, `airflow-dag-processor`, `airflow-scheduler`, dan `airflow-webserver`. `pipeline`, `airflow-init`, dan `airflow-db-bootstrap` dapat berstatus `Exited 0` karena memang berjalan satu kali.

## Menjalankan dan memeriksa pipeline

```powershell
.\env\Scripts\python.exe -m pipeline.runner
.\env\Scripts\python.exe .\scripts\check_warehouse.py
.\env\Scripts\python.exe .\scripts\check_freshness.py
.\env\Scripts\python.exe .\scripts\monitor_pipeline.py
```

Gunakan `--follow 10` pada `monitor_pipeline.py` untuk memperbarui status setiap 10 detik.

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

`SUCCESS` dengan `extracted_records = 0` berarti source tidak berubah. Ini bukan kegagalan dan data lama tidak diproses ulang.

Lihat tahap detail pada `audit.pipeline_stage_runs`. Log lokal berada di `logs/pipeline.log` dan `logs/dashboard.log`.

## Jika pipeline gagal

1. Baca `error_message` pada `audit.pipeline_runs`.
2. Baca stage gagal pada `audit.pipeline_stage_runs`.
3. Periksa `logs/pipeline.log`.
4. Perbaiki source, konfigurasi, atau service yang gagal.
5. Jalankan ulang pipeline. Proses aman diulang karena incremental dan idempotent.

Jangan menghapus fact atau volume PostgreSQL sebagai langkah awal pemulihan.

## Airflow

DAG `ecommerce_sales_pipeline` berada di `airflow/orchestration.py` dan berjalan setiap hari pukul 13.00 WIB. Airflow adalah sumber kebenaran untuk mengaktifkan, menonaktifkan, atau mengubah jadwal DAG.

Jika file DAG atau Docker Compose berubah, jalankan `docker compose up -d --force-recreate airflow-dag-processor airflow-scheduler airflow-webserver`.

Periksa Airflow di `http://127.0.0.1:8080` dan health endpoint di `http://127.0.0.1:8080/api/v2/monitor/health`.

## Email dan alert

Laporan email memakai konfigurasi SMTP di `.env`. Bila Gmail menolak dengan kode `534 5.7.9`, buat App Password baru dan isi `SMTP_PASSWORD` dengan nilai tersebut. Email gagal tidak membatalkan pipeline; detailnya dicatat sebagai `pipeline_email_failed` di log.

`ALERT_WEBHOOK_URL` bersifat opsional untuk notifikasi kegagalan melalui webhook.

## Migration dan deployment

Sebelum memakai kode baru pada database yang sudah ada, jalankan `.\env\Scripts\python.exe -m alembic upgrade head`.

Restart backend lokal setelah perubahan Python. Untuk deployment Docker, lakukan build atau recreate service yang berubah. Jangan commit `.env`, log, atau credential.
