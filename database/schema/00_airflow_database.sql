-- Create a dedicated Airflow metadata database during first PostgreSQL init.
-- The application warehouse remains isolated in ecommerce_sales.
SELECT 'CREATE DATABASE airflow'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'airflow')\gexec
