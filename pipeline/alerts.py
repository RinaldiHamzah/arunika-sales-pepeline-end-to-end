"""Optional operational notifications without making alerts a pipeline dependency."""

import json
import os
import smtplib
import socket
from datetime import datetime
from email.message import EmailMessage
from time import sleep
from urllib.request import Request, urlopen

from pipeline.logger import get_logger
from pipeline.reporting import outcome_message

LOGGER = get_logger("pipeline.alerts")


def _connect_smtp(host: str, port: int):
    """Open SMTP with bounded retries for transient DNS/network failures.

    Only the connection phase is retried.  Retrying after ``send_message``
    could produce duplicate notification emails when a server accepted the
    message but its acknowledgement was lost.
    """
    retries = max(1, int(os.getenv("SMTP_CONNECT_RETRIES", "3")))
    last_error = None
    for attempt in range(1, retries + 1):
        try:
            return smtplib.SMTP(host, port, timeout=15)
        except (OSError, smtplib.SMTPConnectError) as error:
            last_error = error
            if attempt == retries:
                break
            LOGGER.warning(
                "pipeline_email_connect_retry",
                extra={
                    "smtp_host": host,
                    "smtp_port": port,
                    "attempt": attempt,
                    "max_attempts": retries,
                    "error_message": str(error),
                },
            )
            sleep(attempt)
    raise last_error or socket.gaierror("SMTP connection could not be established")


def notify_pipeline_failure(run_id, error_message):
    webhook = os.getenv("ALERT_WEBHOOK_URL", "").strip()
    if not webhook:
        return False
    payload = json.dumps({"text": f"Arunika pipeline FAILED: run_id={run_id}; error={error_message}"}).encode()
    try:
        request = Request(webhook, data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urlopen(request, timeout=5):
            return True
    except Exception:
        return False


def send_pipeline_report(report: dict) -> bool:
    """Email one concise pipeline report using SMTP when it is configured.

    Missing or invalid SMTP settings only skip the alert. They never change the
    result of the warehouse pipeline itself.
    """
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    sender = os.getenv("SMTP_FROM", username).strip()
    recipients = [item.strip() for item in os.getenv("PIPELINE_REPORT_RECIPIENTS", "").split(",") if item.strip()]
    if not all((host, username, password, sender, recipients)):
        LOGGER.warning("pipeline_email_skipped", extra={"status": report.get("status")})
        return False

    status = str(report.get("status", "UNKNOWN")).upper()
    message = EmailMessage()
    message["Subject"] = f"PT Arunika Beauty Indonesia — PIPELINE {status} — {report.get('started_at', 'WIB')}"
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(format_pipeline_report(report))
    port = int(os.getenv("SMTP_PORT", "587"))
    try:
        with _connect_smtp(host, port) as client:
            if os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}:
                client.starttls()
            client.login(username, password)
            client.send_message(message)
        LOGGER.info("pipeline_email_sent", extra={"run_id": str(report.get("run_id")), "status": status})
        return True
    except (OSError, smtplib.SMTPException, ValueError) as error:
        LOGGER.warning(
            "pipeline_email_failed",
            extra={
                "run_id": str(report.get("run_id")),
                "status": status,
                "smtp_host": host,
                "smtp_port": port,
                "error_message": str(error),
            },
        )
        return False


def format_pipeline_report(report):
    """Pure formatter: no SMTP side effects; shared metric names with the UI."""

    def metric(key):
        value = report.get(key)
        return "Belum direkam" if value is None else str(value)

    def duration():
        started = report.get("started_at")
        ended = report.get("ended_at")
        try:
            start_time = datetime.fromisoformat(str(started).replace("Z", "+00:00"))
            end_time = datetime.fromisoformat(str(ended).replace("Z", "+00:00"))
            seconds = (end_time - start_time).total_seconds()
            if seconds >= 0:
                return f"{seconds:.3f} detik"
        except (TypeError, ValueError):
            pass
        value = report.get("duration_seconds")
        return "Belum direkam" if value is None else f"{value} detik"

    status = str(report.get("status", "UNKNOWN")).upper()
    status_label = {"SUCCESS": "BERHASIL", "FAILED": "GAGAL"}.get(status, status)
    if status == "FAILED":
        summary = "Pipeline gagal. Periksa alasan kegagalan di bagian akhir laporan."
    elif report.get("extracted_records") == 0:
        summary = "Pipeline berjalan normal. Tidak ada data baru atau perubahan yang perlu dimuat."
    elif report.get("loaded_records", 0):
        summary = "Pipeline berhasil. Data baru atau perubahan telah diproses ke warehouse."
    else:
        summary = "Pipeline selesai. Tidak ada fact baru yang ditulis ke warehouse."

    explanation = (
        outcome_message(report)
        if status == "FAILED"
        else (report.get("outcome_message") or outcome_message(report))
    )
    lines = [
        "PT Arunika Beauty Indonesia",
        f"{status} — {report.get('started_at', 'WIB')}",
        "Laporan Pipeline Harian",
        "",
        f"Status: {status_label}",
        f"Kesimpulan: {summary}",
        "",
        "WAKTU EKSEKUSI",
        f"Run ID: {report.get('run_id', '—')}",
        f"Mulai: {report.get('started_at', '—')}",
        f"Selesai: {report.get('ended_at', '—')}",
        f"Durasi: {duration()}",
        "",
        "RINGKASAN PEMROSESAN",
        f"Total transaksi diperiksa: {metric('source_records')}",
        f"Data identik dilewati: {metric('skipped_unchanged_records')}",
        f"Data baru/berubah: {metric('extracted_records')}",
        f"Data valid: {metric('validated_records')}",
        f"Data ditolak: {metric('rejected_records')}",
        f"Duplikat saat validasi: {metric('duplicate_records')}",
        f"Kandidat ke warehouse: {metric('incremental_records')}",
        f"Data identik di warehouse: {metric('fact_skipped_records')}",
        f"Data ditulis ke warehouse: {metric('loaded_records')}",
        f"Fact baru: {metric('fact_inserted_records')}",
        "",
        "CATATAN",
        f"{explanation}",
        "Total transaksi tidak termasuk Master Produk.",
        "Baris identik dilewati sebelum validasi ulang; hasil validasi terdahulu tetap berlaku.",
        "",
        "RINGKASAN PER SUMBER",
    ]
    for source in report.get("source_metrics") or []:
        lines.append(
            f"{source['source_name']}: total {source['source_records']}; "
            f"identik {source['skipped_unchanged_records']}; "
            f"kandidat {source['extracted_records']}; "
            f"valid {source.get('validated_records', 'belum diperiksa')}; "
            f"ditolak {source.get('rejected_records', 'belum diperiksa')}; "
            f"duplikat {source.get('duplicate_records', 'belum diperiksa')}"
        )
    if status == "FAILED":
        lines.extend(["", "ERROR", f"Alasan: {report.get('error_message') or 'Tidak diketahui'}"])
    return "\n".join(lines)
