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
from pipeline.reporting import QUALITY_SECTIONS, outcome_message, run_report_summary

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
    message["Subject"] = f"PT Arunika Beauty Indonesia [PIPELINE {status}] {report.get('started_at', 'WIB')}"
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
            "pipeline_email_failed: %s",
            error,
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
    explanation = (
        outcome_message(report) if status == "FAILED" else (report.get("outcome_message") or outcome_message(report))
    )
    run_summary = report.get("report_summary")
    if not isinstance(run_summary, dict):
        run_summary = run_report_summary(report)
    raw = run_summary.get("raw") or {}
    product_master = raw.get("product_master") or {}
    quality_staging = run_summary.get("quality_staging")
    warehouse = run_summary.get("warehouse") or {}

    lines = [
        "PT Arunika Beauty Indonesia",
        f"PIPELINE {status} — {report.get('started_at', 'WIB')}",
        "LAPORAN HARIAN DATA PIPELINE",
        "",
        "WAKTU EKSEKUSI",
        f"Run ID: {report.get('run_id', '—')}",
        f"Mulai: {report.get('started_at', '—')}",
        f"Selesai: {report.get('ended_at', '—')}",
        f"Durasi: {duration()}",
        "",
        "RAW LAYER",
        f"Total transaksi Raw Layer: {raw.get('total_transactions_in_raw', '—')}",
        f"Transaksi baru atau berubah: {raw.get('new_or_changed', metric('extracted_records'))}",
        f"Transaksi dimuat ke Raw Layer: {raw.get('inserted_to_raw', '—')}",
        f"Total Master Produk Raw Layer: {product_master.get('total_in_raw', '—')}",
        f"Master Produk diproses: {product_master.get('new_or_changed', 0)}",
        f"Master Produk dimuat ke Raw Layer: {product_master.get('inserted_to_raw', 0)}",
        "",
    ]
    if quality_staging and raw.get("new_or_changed", report.get("extracted_records", 0)):
        lines.extend(["", "DATA QUALITY"])
        findings = []
        for key, label in QUALITY_SECTIONS:
            finding = quality_staging.get(key) or {}
            if finding.get("total"):
                fields = ", ".join(f"{field}: {count}" for field, count in finding.get("by_field", {}).items())
                findings.append(f"{label}: {finding['total']}" + (f" ({fields})" if fields else ""))
        lines.extend(findings or ["Tidak ada temuan quality check yang memblokir data."])
        lines.extend(
            [
                "",
                "STAGING LAYER",
                f"Lolos ke staging: {quality_staging.get('passed_to_staging', 0)}",
                f"Diload ke staging: {quality_staging.get('written_to_staging', 0)}",
                "",
                "WAREHOUSE",
                f"Fact siap dimuat: {warehouse.get('eligible_facts', 0)}",
                f"Fact baru: {warehouse.get('inserted_facts', 0)}",
                f"Total fact ditulis: {warehouse.get('facts_written', 0)}",
                "",
                "CATATAN AUDIT",
                f"{explanation}",
            ]
        )
    elif status != "FAILED" and not raw.get("new_or_changed", report.get("extracted_records", 0)):
        lines.extend(
            [
                "",
                "CATATAN AUDIT",
                f"{explanation}",
                ""
            ]
        )
    elif status != "FAILED":
        lines.extend(["", "QUALITY CHECK & STAGING", "Rincian quality run lama tidak tersedia di audit."])
    if status == "FAILED":
        lines.extend(["", "ERROR", f"Alasan: {report.get('error_message') or 'Tidak diketahui'}"])
    return "\n".join(lines)
