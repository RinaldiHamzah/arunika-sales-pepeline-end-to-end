"""One PostgreSQL lock shared by CLI, dashboard and Airflow processes."""

from contextlib import contextmanager
from uuid import uuid4

from sqlalchemy import text

LOCK_KEY = 82462731


class PipelineBusyError(RuntimeError):
    pass


def try_transaction_lock(connection):
    return connection.execute(text("SELECT pg_try_advisory_xact_lock(:key)"), {"key": LOCK_KEY}).scalar_one()


def recover_abandoned_runs(connection):
    """Call only while holding the shared lock: no live runner can be stopped."""
    connection.execute(
        text("""
        UPDATE audit.pipeline_runs
        SET status='FAILED', ended_at=CURRENT_TIMESTAMP, current_stage='failed',
            error_message='Previous process ended without completing its audit.',
            duration_seconds=EXTRACT(EPOCH FROM (CURRENT_TIMESTAMP-started_at))
        WHERE status='RUNNING' AND (
            current_stage <> 'queued' OR
            started_at < CURRENT_TIMESTAMP - INTERVAL '60 seconds'
        )
    """)
    )


def reserve_run(connection, pipeline_name):
    """Serialize check + reservation; the child claims this exact UUID."""
    if not try_transaction_lock(connection):
        raise PipelineBusyError("Pipeline sedang berjalan.")
    recover_abandoned_runs(connection)
    if connection.execute(text("SELECT EXISTS(SELECT 1 FROM audit.pipeline_runs WHERE status='RUNNING')")).scalar_one():
        raise PipelineBusyError("Pipeline sedang menunggu atau berjalan.")
    run_id = uuid4()
    connection.execute(
        text("""
        INSERT INTO audit.pipeline_runs
            (run_id, pipeline_name, status, current_stage, current_stage_started_at)
        VALUES (:run_id, :name, 'RUNNING', 'queued', CURRENT_TIMESTAMP)
    """),
        {"run_id": run_id, "name": pipeline_name},
    )
    return run_id


@contextmanager
def pipeline_lock(engine):
    # A dedicated session owns the lock for the entire run, across commits.
    with engine.connect() as connection:
        acquired = connection.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": LOCK_KEY}).scalar_one()
        connection.commit()
        if not acquired:
            raise PipelineBusyError("Pipeline sedang berjalan; coba lagi setelah selesai.")
        try:
            yield
        finally:
            try:
                connection.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": LOCK_KEY})
                connection.commit()
            except Exception:
                # Never return a session with a potentially held lock to the pool.
                connection.invalidate()


def begin_run(engine, pipeline_name, reserved_run_id=None, orchestration_run_id=None):
    """Must be called under pipeline_lock."""
    with engine.begin() as connection:
        if reserved_run_id:
            claimed = connection.execute(
                text("""
                UPDATE audit.pipeline_runs
                SET current_stage='starting', current_stage_started_at=CURRENT_TIMESTAMP
                WHERE run_id=:run_id AND pipeline_name=:name
                    AND status='RUNNING' AND current_stage='queued'
                RETURNING run_id
            """),
                {"run_id": reserved_run_id, "name": pipeline_name},
            ).scalar_one_or_none()
            if claimed is None:
                raise PipelineBusyError("Reservation sudah selesai atau kedaluwarsa.")
            return claimed
        recover_abandoned_runs(connection)
        if connection.execute(
            text("SELECT EXISTS(SELECT 1 FROM audit.pipeline_runs WHERE status='RUNNING')")
        ).scalar_one():
            raise PipelineBusyError("Pipeline sudah memiliki reservation.")
        return connection.execute(
            text("""
            INSERT INTO audit.pipeline_runs
                (pipeline_name, status, current_stage, current_stage_started_at, orchestration_run_id)
            VALUES (:name, 'RUNNING', 'starting', CURRENT_TIMESTAMP, :orchestration)
            RETURNING run_id
        """),
            {"name": pipeline_name, "orchestration": orchestration_run_id},
        ).scalar_one()
