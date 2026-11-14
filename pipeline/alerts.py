"""Notifikasi operasional pipeline."""

import json
import os
import smtplib
import socket
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from time import sleep
from urllib.request import Request, urlopen

from jinja2 import Environment, FileSystemLoader, select_autoescape

from pipeline.logger import get_logger
from pipeline.reporting import outcome_message, run_report_summary

LOGGER = get_logger("pipeline.alerts")
_EMAIL_TEMPLATE_ENV = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(("html", "xml")),
)


def _connect_smtp(host: str, port: int, username: str, password: str, use_tls: bool):
    """Hubungkan, lakukan negosiasi TLS, dan autentikasi dengan percobaan terbatas.

    Pesan baru dikirim setelah fungsi ini berhasil. Percobaan ulang setelah
    ``send_message`` dapat mengirim email ganda jika server sudah menerima pesan,
    tetapi tanda terimanya hilang.
    """
    retries = max(1, int(os.getenv("SMTP_CONNECT_RETRIES", "3")))
    last_error = None
    for attempt in range(1, retries + 1):
        client = None
        try:
            client = smtplib.SMTP(host, port, timeout=15)
            if use_tls:
                client.starttls()
            client.login(username, password)
            return client
        except (OSError, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected) as error:
            last_error = error
            if client is not None:
                try:
                    client.close()
                except OSError:
                    pass
            if attempt == retries:
                break
            LOGGER.warning(
                "pipeline_email_session_retry",
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
    """Kirim satu laporan pipeline yang ringkas melalui SMTP jika sudah dikonfigurasi.

    Pengaturan SMTP yang kosong atau tidak valid hanya membuat alert dilewati.
    Kondisi tersebut tidak mengubah hasil pipeline gudang data.
    """
    host = os.getenv("SMTP_HOST", "").strip()
    username = os.getenv("SMTP_USERNAME", "").strip()
    password = os.getenv("SMTP_PASSWORD", "")
    if host.lower() == "smtp.gmail.com":
        # Google menampilkan App Password dalam kelompok; spasi bukan bagian dari sandi.
        password = "".join(password.split())
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
    message.add_alternative(format_pipeline_report_html(report), subtype="html")
    port = int(os.getenv("SMTP_PORT", "587"))
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in {"1", "true", "yes"}
    try:
        with _connect_smtp(host, port, username, password, use_tls) as client:
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
    """Format laporan email dengan susunan metrik yang konsisten dengan logger."""

    def duration():
        try:
            start = datetime.fromisoformat(str(report.get("started_at")).replace("Z", "+00:00"))
            end = datetime.fromisoformat(str(report.get("ended_at")).replace("Z", "+00:00"))
            seconds = (end - start).total_seconds()
            if seconds >= 0:
                return f"{seconds:.3f} detik"
        except (TypeError, ValueError):
            pass
        value = report.get("duration_seconds")
        return "Belum direkam" if value is None else f"{value} detik"

    def count(value):
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    status = str(report.get("status", "UNKNOWN")).upper()
    explanation = outcome_message(report) if status == "FAILED" else (
        report.get("outcome_message") or outcome_message(report)
    )
    summary = report.get("report_summary")
    if not isinstance(summary, dict):
        summary = run_report_summary(report)
    raw = summary.get("raw") or {}
    product = raw.get("product_master") or {}
    quality = summary.get("quality_staging")
    warehouse = summary.get("warehouse") or {}
    return_warehouse = summary.get("return_warehouse") or {}
    dimensions = summary.get("dimensions") or {}
    database_counts = summary.get("database_table_counts") or {}
    auxiliary = {
        item.get("source_name"): item
        for item in (summary.get("auxiliary_sources") or [])
        if isinstance(item, dict)
    }
    promo = auxiliary.get("PROMO_MASTER", {})
    returns = auxiliary.get("RETURN_EVENTS", {})
    source_by_name = {
        item.get("source_name"): item
        for item in (report.get("source_metrics") or [])
        if isinstance(item, dict)
    }
    channels = ("SHOPEE", "TOKOPEDIA", "WEBSITE", "OFFLINE_STORE")
    sales_candidates = sum(count(source_by_name.get(name, {}).get("extracted_records")) for name in channels)
    if not any(name in source_by_name for name in channels):
        sales_candidates = count(report.get("extracted_records"))
    product_candidate = count(source_by_name.get("PRODUCT_MASTER", {}).get("extracted_records"))
    promo_candidate = count(promo.get("processed"))
    return_candidate = count(returns.get("processed"))
    all_candidates = sales_candidates + product_candidate + promo_candidate + return_candidate
    sales_valid = sum(count(source_by_name.get(name, {}).get("validated_records")) for name in channels)
    if not any(name in source_by_name for name in channels):
        sales_valid = count(report.get("validated_records"))
    all_valid = sales_valid + count(source_by_name.get("PRODUCT_MASTER", {}).get("validated_records")) + count(promo.get("validated")) + count(returns.get("validated"))
    all_rejected = (
        (
            sum(count(source_by_name.get(name, {}).get("rejected_records")) for name in (*channels, "PRODUCT_MASTER"))
            if source_by_name else count(report.get("rejected_records"))
        )
        + count(promo.get("rejected")) + count(returns.get("rejected"))
    )
    all_duplicates = (
        (
            sum(count(source_by_name.get(name, {}).get("duplicate_records")) for name in (*channels, "PRODUCT_MASTER"))
            if source_by_name else count(report.get("duplicate_records"))
        )
        + count(promo.get("duplicates")) + count(returns.get("duplicates"))
    )

    lines = [
        "PT Arunika Beauty Indonesia",
        f"PIPELINE {status} — {report.get('started_at', 'WIB')}",
        "LAPORAN HARIAN DATA PIPELINE", "",
        "WAKTU EKSEKUSI",
        f"Run ID          : {report.get('run_id', '—')}",
        f"Mulai           : {report.get('started_at', '—')}",
        f"Selesai         : {report.get('ended_at', '—')}",
        f"Durasi          : {duration()}", "",
        "RINGKASAN RECORD",
        f"- Kandidat Transaksi kanal : {sales_candidates}",
        f"- Kandidat Master Produk   : {product_candidate}",
        f"- Kandidat Promo baru      : {promo_candidate}",
        f"- Kandidat Return baru     : {return_candidate}",
        f"- Total baris semua sumber : {all_candidates}",
        f"- Total valid              : {all_valid}",
        f"- Total ditolak            : {all_rejected}",
        f"- Total duplikat           : {all_duplicates}",
        f"- Fact Sales ditulis       : {count(warehouse.get('facts_written', report.get('loaded_records')))}",
        f"- Fact Return ditulis      : {count(return_warehouse.get('facts_written', returns.get('warehouse_written')))}", "",
        "RINCIAN PER SUMBER",
    ]

    for name in ("PRODUCT_MASTER", "PROMO_MASTER", *channels, "RETURN_EVENTS"):
        source = source_by_name.get(name)
        if name == "PROMO_MASTER":
            source = promo
            if source:
                details = []
                if count(source.get("raw_inserted")):
                    details.append(f"Raw ditambah {source['raw_inserted']}")
                if count(source.get("warehouse_written")):
                    details.append(f"Dimensi Promo diproses {source['warehouse_written']}")
                if count(source.get("promo_codes_checked")):
                    details.append(f"Kode promo cocok {count(source.get('promo_codes_matched'))}/{source['promo_codes_checked']}")
                lines.append(
                    f"- Master Promo: katalog {source.get('source_records', 0)} | valid katalog {source.get('catalog_validated', source.get('validated', 0))} | "
                    f"baru/berubah {source.get('processed', 0)} | ditolak {source.get('rejected', 0)} | duplikat {source.get('duplicates', 0)}"
                    + (" | " + " | ".join(details) if details else "")
                )
            else:
                lines.append("- Master Promo: belum ada metrik.")
            continue
        if name == "RETURN_EVENTS":
            source = returns
            if source:
                details = [f"{label} {source[key]}" for key, label in (
                    ("raw_inserted", "Raw ditambah"), ("staging_written", "Staging dimuat"), ("warehouse_written", "Fact ditulis")
                ) if count(source.get(key))]
                lines.append(
                    f"- Return: sumber {source.get('source_records', 0)} | berubah {source.get('processed', 0)} | "
                    f"valid {source.get('validated', 0)} | ditolak {source.get('rejected', 0)} | duplikat {source.get('duplicates', 0)}"
                    + (" | " + " | ".join(details) if details else "")
                )
            else:
                lines.append("- Return: belum ada metrik.")
            continue
        if not source:
            lines.append(f"- {'Master Produk' if name == 'PRODUCT_MASTER' else name}: belum ada metrik.")
            continue
        label = "Master Produk" if name == "PRODUCT_MASTER" else name
        extra = ""
        if name == "PRODUCT_MASTER":
            details = []
            if count(product.get("inserted_to_raw")):
                details.append(f"Raw ditambah {product['inserted_to_raw']}")
            if count(dimensions.get("products_processed")):
                details.append(f"Dimensi Produk diproses {dimensions['products_processed']}")
            extra = (" | " + " | ".join(details)) if details else ""
        lines.append(
            f"- {label}: sumber {source.get('source_records', 0)} | kandidat {source.get('extracted_records', 0)} | "
            f"valid {source.get('validated_records', 0)} | ditolak {source.get('rejected_records', 0)} | "
            f"duplikat dilewati {source.get('duplicate_records', 0)}{extra}"
        )

    lines.extend([
        "", "RAW LAYER",
        f"- Transaksi kanal baru/berubah: {raw.get('new_or_changed', 0)} | Raw ditambah {raw.get('inserted_to_raw', 0)} | total Raw: {raw.get('total_transactions_in_raw', '—')}",
        f"- Master Produk baru/berubah: {product.get('new_or_changed', 0)} | Raw ditambah {product.get('inserted_to_raw', 0)} | total Raw: {product.get('total_in_raw', '—')}",
    ])
    if promo:
        lines.append(f"- Master Promo baru/berubah: {promo.get('processed', 0)} | Raw ditambah {promo.get('raw_inserted', 0)} | total Raw: {database_counts.get('raw.promo_master', '—')}")
    if returns:
        lines.append(f"- Return baru/berubah: {returns.get('processed', 0)} | Raw ditambah {returns.get('raw_inserted', 0)} | total Raw: {database_counts.get('raw.return_events', '—')}")

    lines.extend(["", "QUALITY CHECK — SALES"])
    if isinstance(quality, dict):
        for key, label in (
            ("missing_value", "Nilai kosong"),
            ("duplicate_business_key", "Baris terdampak duplikat business key"),
            ("invalid_quantity", "Kuantitas tidak valid"),
            ("invalid_price", "Harga atau amount tidak valid"),
            ("invalid_status", "Status tidak valid"),
            ("invalid_date", "Tanggal tidak valid"),
            ("unmapped_product", "Produk tidak termapping"),
            ("type_cast_failure", "Gagal konversi tipe"),
        ):
            finding = quality.get(key) or {}
            if finding.get("total"):
                fields = ", ".join(f"{field}: {value}" for field, value in (finding.get("by_field") or {}).items())
                lines.append(f"- {label}: {finding['total']}" + (f" ({fields})" if fields else ""))
        if not any(
            (quality.get(key) or {}).get("total")
            for key in (
                "missing_value", "duplicate_business_key", "invalid_quantity", "invalid_price",
                "invalid_status", "invalid_date", "unmapped_product", "type_cast_failure",
            )
        ):
            lines.append("- Tidak ada temuan quality check.")
    else:
        lines.append("- Tidak dijalankan karena tidak ada data baru atau perubahan.")

    lines.extend(["", "QUALITY CHECK — RETURN"])
    if not returns.get("processed", 0):
        lines.append("- Tidak dijalankan karena tidak ada data baru atau perubahan.")
    else:
        lines.extend([
            f"- Baris sumber: {returns.get('source_records', 0)} | berubah: {returns.get('processed', 0)} | tidak berubah: {returns.get('unchanged', 0)}",
            f"- Diperiksa: {returns.get('processed', 0)}", f"- Valid: {returns.get('validated', 0)}",
            f"- Ditolak: {returns.get('rejected', 0)}", f"- Duplikat: {returns.get('duplicates', 0)}",
        ])
        reasons = returns.get("rejection_reasons") or {}
        if reasons:
            lines.append("- Rincian penolakan: " + " | ".join(f"{reason}: {value}" for reason, value in sorted(reasons.items())))

    lines.extend([
        "", "STAGING LAYER",
        f"- Sales lolos ke Staging: {quality.get('passed_to_staging', 0) if isinstance(quality, dict) else 0}",
        f"- Sales dimuat ke Staging: {quality.get('written_to_staging', 0) if isinstance(quality, dict) else 0}",
        f"- Return lolos ke Staging: {returns.get('validated', 0)}",
        f"- Return dimuat ke Staging: {returns.get('staging_written', 0)}",
        "", "WAREHOUSE LAYER",
        f"- Fact Sales siap dimuat : {warehouse.get('eligible_facts', 0)}",
        f"- Fact Sales baru        : {warehouse.get('inserted_facts', 0)}",
        f"- Fact Sales diperbarui  : {warehouse.get('updated_facts', 0)}",
        f"- Total Fact Sales ditulis: {warehouse.get('facts_written', report.get('loaded_records', 0))}",
        f"- Fact Return siap dimuat: {return_warehouse.get('eligible_facts', returns.get('validated', 0))}",
        f"- Fact Return baru       : {return_warehouse.get('inserted_facts', 0)}",
        f"- Fact Return diperbarui : {return_warehouse.get('updated_facts', 0)}",
        f"- Total Fact Return ditulis: {return_warehouse.get('facts_written', returns.get('warehouse_written', 0))}",
    ])
    if database_counts:
        lines.extend(["", "JUMLAH BARIS DALAM DATABASE"])
        for table in (
            "raw.shopee_orders", "raw.tokopedia_transactions", "raw.website_transactions", "raw.offline_store_sales",
            "raw.product_master", "raw.promo_master", "raw.return_events", "staging.stg_sales", "staging.stg_returns",
            "warehouse.fact_sales", "warehouse.fact_returns",
        ):
            lines.append(f"- {table:<34}: {database_counts.get(table, 'Belum direkam')}")
    if status == "FAILED":
        lines.extend(["", f"ERROR: {report.get('error_message') or 'Tidak diketahui'}"])
    lines.append(f"Kesimpulan: {explanation}")
    return "\n".join(lines)


def format_pipeline_report_html(report):
    """Render laporan teks yang sama sebagai email HTML responsif dan aman."""
    lines = format_pipeline_report(report).splitlines()
    status = str(report.get("status", "UNKNOWN")).upper()
    run_id = str(report.get("run_id") or "—")
    started = str(report.get("started_at") or "Waktu tidak tersedia")
    execution = {}
    in_execution = False
    for line in lines:
        if line.strip() == "WAKTU EKSEKUSI":
            in_execution = True
            continue
        if in_execution and not line.strip():
            break
        if in_execution:
            label, separator, value = line.partition(":")
            if separator:
                execution[label.strip()] = value.strip()
    ended = execution.get("Selesai", "Belum direkam")
    duration_text = execution.get("Durasi", "Belum direkam")
    success = status == "SUCCESS"
    status_color = "#087f5b" if success else "#b42318"
    status_bg = "#e6f4ef" if success else "#fef0ef"

    sections = []
    current_title = None
    current_rows = []
    conclusion = ""
    error = ""
    headings = {
        "RINGKASAN RECORD", "RINCIAN PER SUMBER", "RAW LAYER",
        "QUALITY CHECK — SALES", "QUALITY CHECK — RETURN", "STAGING LAYER",
        "WAREHOUSE LAYER", "JUMLAH BARIS DALAM DATABASE",
    }
    for line in lines[3:]:
        stripped = line.strip()
        if stripped.startswith("Kesimpulan:"):
            conclusion = stripped.partition(":")[2].strip()
            continue
        if stripped.startswith("ERROR:"):
            error = stripped.partition(":")[2].strip()
            continue
        if stripped in headings:
            if current_title is not None:
                sections.append((current_title, current_rows))
            current_title, current_rows = stripped, []
        elif current_title is not None and stripped:
            current_rows.append(stripped.removeprefix("- "))
    if current_title is not None:
        sections.append((current_title, current_rows))

    rendered_sections = []
    for title, rows in sections:
        kind = "summary" if title == "RINGKASAN RECORD" else "sources" if title == "RINCIAN PER SUMBER" else "details"
        normalized_rows = []
        for row in rows:
            label, separator, value = row.partition(":")
            if kind == "sources":
                normalized_rows.append({
                    "label": label.strip() if separator else row,
                    "parts": [part.strip() for part in value.split("|")] if separator else [],
                    "value": value.strip(),
                })
            else:
                normalized_rows.append({
                    "label": label.strip() if separator else "",
                    "value": value.strip() if separator else row,
                })
        rendered_sections.append({"title": title, "kind": kind, "rows": normalized_rows})

    return _EMAIL_TEMPLATE_ENV.get_template("alerts.html").render(
        status=status,
        success=status == "SUCCESS",
        run_id=run_id,
        started=started,
        ended=ended,
        duration=duration_text,
        sections=rendered_sections,
        error=error,
        conclusion=conclusion,
    )
