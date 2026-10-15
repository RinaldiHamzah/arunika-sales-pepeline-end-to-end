-- Buat basis data metadata Airflow terpisah saat inisialisasi PostgreSQL pertama.
-- Gudang data aplikasi tetap terpisah di ecommerce_sales.
SELECT 'CREATE DATABASE airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec
