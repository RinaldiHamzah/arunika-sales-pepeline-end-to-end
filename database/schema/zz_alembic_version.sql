-- Schema bootstrap berisi struktur terbaru, jadi Alembic harus memulai dari head
-- ini alih-alih memutar ulang migrasi historis di atas schema yang sudah lengkap.
-- Prefix zz memastikan file dijalankan setelah seluruh bootstrap SQL lainnya.
CREATE TABLE IF NOT EXISTS public.alembic_version (
    version_num VARCHAR(32) NOT NULL PRIMARY KEY
);

INSERT INTO public.alembic_version (version_num)
SELECT '20261114_21'
WHERE NOT EXISTS (SELECT 1 FROM public.alembic_version);
