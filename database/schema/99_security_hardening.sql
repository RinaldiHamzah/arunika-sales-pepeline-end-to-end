-- Final bootstrap hardening. Public connectivity and schema creation are closed;
-- production role privilege elevation is managed by the cluster administrator.
DO $$
BEGIN
    EXECUTE format('REVOKE CONNECT ON DATABASE %I FROM PUBLIC', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), current_user);
    IF EXISTS (SELECT 1 FROM pg_database WHERE datname = 'airflow') THEN
        REVOKE CONNECT ON DATABASE airflow FROM PUBLIC;
        EXECUTE format('GRANT CONNECT ON DATABASE airflow TO %I', current_user);
    END IF;
END $$;

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
