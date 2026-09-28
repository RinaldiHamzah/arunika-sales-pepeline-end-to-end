# Alembic Database Migration

Folder `alembic/` mengelola perubahan struktur database PostgreSQL yang sudah digunakan oleh aplikasi. Alembic memastikan perubahan seperti penambahan kolom, tabel audit, indeks, atau analytics view dapat diterapkan secara bertahap tanpa menghapus data yang sudah ada.

Pada proyek ini, Alembic digunakan untuk database yang telah berjalan. Sementara itu, file pada [`database/schema/`](../database/schema/) digunakan sebagai bootstrap saat volume PostgreSQL masih benar-benar baru.

## Kapan menggunakan Alembic

Gunakan Alembic ketika database sudah berisi data dan ada perubahan schema yang perlu diterapkan, misalnya:

- menambah kolom audit atau metrik pipeline;
- menambah indeks untuk mempercepat query;
- membuat atau memperbarui analytics view;
- memperbaiki struktur tabel tanpa membuat database dari awal;
- menyamakan database lokal, Docker, dan server deployment ke versi schema yang sama.

Jangan menghapus volume database hanya untuk menerapkan perubahan schema rutin. Jalankan migration yang sesuai agar data transaksi, audit, dan warehouse tetap terjaga.

## Struktur folder

```text
alembic/
├── env.py
├── script.py.mako
├── versions/
│   ├── metrics_and_hashes.py
│   ├── security_hardening.py
│   ├── stage_observability.py
│   ├── live_pipeline_progress.py
│   ├── normalize_city_values.py
│   ├── snapshot_state.py
│   ├── incremental_reporting.py
│   ├── analytics_and_quality_views.py
│   ├── quality_report_detail.py
│   └── run_report_summary.py
└── README.md
```

| File atau folder | Fungsi |
| --- | --- |
| `env.py` | Membaca konfigurasi database dari `pipeline.config.settings`, lalu membuka koneksi yang dipakai Alembic. |
| `script.py.mako` | Template standar bila migration baru dibuat dengan Alembic. |
| `versions/` | Kumpulan revision migration yang dijalankan secara berurutan. |
| `README.md` | Panduan penggunaan migration pada proyek ini. |

Nama file dibuat berdasarkan fungsi perubahan agar mudah dibaca. Urutan migration **tidak ditentukan oleh nama file**, melainkan oleh nilai `revision` dan `down_revision` di dalam setiap file.

## Riwayat migration

| Revision | File | Ringkasan perubahan |
| --- | --- | --- |
| `20260917_01` | `metrics_and_hashes.py` | Menambahkan metrik operasional dan hash untuk kebutuhan incremental loading. |
| `20260917_02` | `security_hardening.py` | Memperketat hak akses role database aplikasi. |
| `20260917_03` | `stage_observability.py` | Menambahkan pencatatan observability untuk setiap tahap pipeline. |
| `20260920_04` | `live_pipeline_progress.py` | Menyimpan tahap pipeline aktif untuk status proses pada dashboard. |
| `20260920_05` | `normalize_city_values.py` | Menormalisasi nilai kota lama pada dimensi customer. |
| `20260920_06` | `snapshot_state.py` | Menyimpan snapshot source dan korelasi run Airflow. |
| `20260922_07` | `incremental_reporting.py` | Menambahkan metrik pelaporan incremental sebelum validasi. |
| `20260925_08` | `analytics_and_quality_views.py` | Menambahkan SQL analytics views dan view laporan quality check. |
| `20260925_09` | `quality_report_detail.py` | Menambahkan laporan data quality detail per source dan aturan. |
| `20260926_10` | `run_report_summary.py` | Menambahkan ringkasan Raw, Quality/Staging, dan Warehouse per run. |

Revision terbaru saat ini adalah `20260926_10`.

## Perintah yang digunakan

Aktifkan virtual environment terlebih dahulu bila belum aktif:

```powershell
.\env\Scripts\Activate.ps1
```

Lihat revision database yang sedang digunakan:

```powershell
.\env\Scripts\python.exe -m alembic current
```

Lihat seluruh riwayat migration:

```powershell
.\env\Scripts\python.exe -m alembic history
```

Lihat revision terbaru yang tersedia di source code:

```powershell
.\env\Scripts\python.exe -m alembic heads
```

Terapkan seluruh migration yang belum ada pada database:

```powershell
.\env\Scripts\python.exe -m alembic upgrade head
```

Untuk menjalankan database melalui Docker Compose, pipeline dan integration test sudah memanggil `alembic upgrade head` sebelum proses utama dijalankan.

## Membuat migration baru

Saat ada perubahan schema baru, buat satu file migration yang menjelaskan satu tujuan bisnis atau teknis dengan jelas.

```powershell
.\env\Scripts\python.exe -m alembic revision -m "deskripsi_perubahan"
```

Kemudian lengkapi fungsi berikut pada file baru:

```python
def upgrade() -> None:
    # Perubahan schema yang diterapkan ke depan.
    pass


def downgrade() -> None:
    # Kebalikan perubahan bila rollback memang aman dilakukan.
    pass
```

Setelah itu, uji migration pada database pengujian terlebih dahulu. Jangan langsung menerapkan perubahan yang belum diuji ke database yang dipakai dashboard atau pipeline harian.

## Aturan penting

1. Jangan mengubah nilai `revision` atau `down_revision` pada migration yang sudah pernah diterapkan. Database menyimpan ID tersebut pada tabel `alembic_version`.
2. Jangan mengedit migration lama untuk mengubah schema yang telah digunakan. Buat revision baru agar riwayat perubahan tetap dapat diaudit.
3. Hindari operasi destruktif seperti `DROP TABLE`, penghapusan kolom, atau perubahan tipe data tanpa backup dan rencana rollback.
4. Gunakan `IF EXISTS`, `IF NOT EXISTS`, atau pemeriksaan kondisi bila migration perlu aman dijalankan pada database yang sudah memiliki sebagian struktur lama.
5. Untuk perubahan view, pastikan query dapat dijalankan pada database pengujian dan tetap sesuai dengan dashboard maupun laporan quality check.
6. Setelah migration baru dibuat, jalankan `alembic upgrade head`, lalu periksa `alembic current` untuk memastikan database berada di revision terbaru.

## Catatan tentang `alembic check`

Perintah `alembic check` tidak digunakan sebagai validasi utama pada proyek ini. Proyek memakai schema SQL dan migration manual, bukan model ORM SQLAlchemy yang menyediakan `MetaData`. Karena `target_metadata` pada `env.py` bernilai `None`, Alembic tidak dapat melakukan perbandingan autogenerate antara model ORM dan database.

Validasi yang sesuai untuk proyek ini adalah:

```powershell
.\env\Scripts\python.exe -m alembic heads
.\env\Scripts\python.exe -m alembic current
.\env\Scripts\python.exe -m alembic upgrade head
.\env\Scripts\python.exe scripts\validate_sql.py
```

Jika `current` dan `heads` menunjukkan revision yang sama, berarti database sudah berada pada struktur migration terbaru.
