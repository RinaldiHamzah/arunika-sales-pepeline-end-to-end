"""One reporting vocabulary for the runner, dashboard and daily email."""

QUALITY_SECTIONS = (
    ("missing_value", "Nilai wajib kosong"),
    ("duplicate_business_key", "Duplikat business key"),
    ("invalid_quantity", "Kuantitas tidak valid"),
    ("invalid_price", "Harga atau nilai transaksi tidak valid"),
    ("invalid_status", "Status tidak valid"),
    ("invalid_date", "Tanggal tidak valid"),
    ("unmapped_product", "Produk tidak termapping"),
    ("type_cast_failure", "Konversi tipe gagal"),
)

RESULT_SOURCE_NAMES = {
    "shopee": "SHOPEE",
    "tokopedia": "TOKOPEDIA",
    "website": "WEBSITE",
    "offline": "OFFLINE_STORE",
    "product": "PRODUCT_MASTER",
}


def _count(report, key):
    """Return a non-negative integer metric when a run recorded it."""
    value = report.get(key)
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return None


def _source_metric(report: dict, source_name: str, key: str) -> int:
    """Return one non-negative metric from a recorded source summary."""
    for source in report.get("source_metrics") or []:
        if source.get("source_name") == source_name:
            try:
                return max(0, int(source.get(key) or 0))
            except (TypeError, ValueError):
                return 0
    return 0


def summarize_sources(scanned, candidates):
    counts = {source.source_name: len(source.frame) for source in candidates}
    details = []
    for source in scanned:
        total = source.source_records if source.source_records is not None else len(source.frame)
        candidate = counts[source.source_name]
        details.append(
            {
                "source_name": source.source_name,
                "source_records": total,
                "skipped_unchanged_records": total - candidate,
                "extracted_records": candidate,
            }
        )
    sales = [row for row in details if row["source_name"] != "PRODUCT_MASTER"]
    return {
        "source_records": sum(row["source_records"] for row in sales),
        "skipped_unchanged_records": sum(row["skipped_unchanged_records"] for row in sales),
        "source_metrics": details,
    }


def _quality_section(rule: object, field: object) -> str:
    """Map a technical validation finding to one user-facing report section."""
    rule_name = str(rule)
    field_name = str(field).lower()
    if rule_name in {"MISSING_REQUIRED", "MISSING_OPTIONAL"}:
        return "missing_value"
    if rule_name in {"DUPLICATE_BUSINESS_KEY", "CONFLICTING_DUPLICATE"}:
        return "duplicate_business_key"
    if rule_name == "INVALID_DATE":
        return "invalid_date"
    if rule_name == "INVALID_STATUS":
        return "invalid_status"
    if rule_name == "UNMAPPED_PRODUCT":
        return "unmapped_product"
    if field_name in {"qty", "quantity", "units"}:
        return "invalid_quantity"
    if field_name in {"price", "unit_price", "item_price", "total_amount"}:
        return "invalid_price"
    if rule_name in {"INVALID_NUMBER", "INVALID_INTEGER", "INVALID_MONEY_PRECISION_OR_RANGE"}:
        return "type_cast_failure"
    return "type_cast_failure"


def _empty_quality_sections() -> dict:
    return {key: {"total": 0, "by_field": {}} for key, _ in QUALITY_SECTIONS}


def _summarize_quality_issues(issues) -> dict:
    sections = _empty_quality_sections()
    if issues.empty:
        return sections
    for issue in issues.to_dict("records"):
        key = _quality_section(issue.get("rule"), issue.get("field"))
        field = str(issue.get("field") or "tidak diketahui")
        sections[key]["total"] += 1
        sections[key]["by_field"][field] = sections[key]["by_field"].get(field, 0) + 1
    return sections


def quality_staging_summary(results, *, passed_to_staging: int, written_to_staging: int) -> dict:
    """Create one explicit quality/staging result from validation evidence."""
    sections = _empty_quality_sections()
    by_source = []
    for source, result in results.items():
        source_sections = _summarize_quality_issues(result.issues)
        summary = result.summary
        by_source.append(
            {
                "source_name": RESULT_SOURCE_NAMES[source],
                "processed": int(summary.get("extracted_records", 0)),
                "valid": int(summary.get("valid_records", 0)),
                "rejected": int(summary.get("invalid_records", 0)),
                "duplicate": int(summary.get("duplicate_records", 0)),
                "issues": source_sections,
            }
        )
        # Product Master is quality-checked and shown in its own detail card,
        # but it never creates transaction staging rows. Do not include it in
        # transaction-level Quality/Staging totals.
        if source != "product":
            for key, _ in QUALITY_SECTIONS:
                sections[key]["total"] += source_sections[key]["total"]
                for field, count in source_sections[key]["by_field"].items():
                    sections[key]["by_field"][field] = sections[key]["by_field"].get(field, 0) + count
    return {
        "checked": True,
        **sections,
        "by_source": by_source,
        "passed_to_staging": max(0, int(passed_to_staging)),
        "written_to_staging": max(0, int(written_to_staging)),
    }


def run_report_summary(
    report: dict,
    *,
    raw_inserted_records: int = 0,
    raw_transaction_total: int | None = None,
    raw_product_master_total: int | None = None,
    raw_inserted_product_master_records: int = 0,
    quality_staging: dict | None = None,
    eligible_facts: int = 0,
    inserted_facts: int = 0,
    facts_written: int = 0,
) -> dict:
    """Build the durable Raw → Quality/Staging → Warehouse run report.

    Processing metrics describe this run. Transaction and Product Master
    inventory are separate so reference records never inflate sales metrics.
    """
    written = max(0, int(facts_written))
    inserted = max(0, int(inserted_facts))
    return {
        "raw": {
            "source_total": _count(report, "source_records") or 0,
            "new_or_changed": _count(report, "extracted_records") or 0,
            "inserted_to_raw": max(0, int(raw_inserted_records)),
            "total_transactions_in_raw": None if raw_transaction_total is None else max(0, int(raw_transaction_total)),
            "product_master": {
                "source_total": _source_metric(report, "PRODUCT_MASTER", "source_records"),
                "new_or_changed": _source_metric(report, "PRODUCT_MASTER", "extracted_records"),
                "inserted_to_raw": max(0, int(raw_inserted_product_master_records)),
                "total_in_raw": (None if raw_product_master_total is None else max(0, int(raw_product_master_total))),
            },
        },
        "quality_staging": quality_staging,
        "warehouse": {
            "eligible_facts": max(0, int(eligible_facts)),
            "inserted_facts": inserted,
            "updated_facts": max(0, written - inserted),
            "facts_written": written,
        },
    }


def outcome_message(report):
    if report.get("status") == "FAILED":
        return "Pipeline gagal. Lihat alasan kegagalan; data belum tentu sudah divalidasi."
    extracted_records = _count(report, "extracted_records")
    if extracted_records is None:
        return "Run lama: jumlah data yang diproses belum direkam."
    if extracted_records == 0:
        return "Pipeline selesai tanpa data baru atau perubahan untuk diproses."
    product_master_records = _source_metric(report, "PRODUCT_MASTER", "extracted_records")
    product_context = (
        f" Master Produk: {product_master_records} record diproses untuk mapping produk."
        if product_master_records
        else ""
    )
    if report.get("loaded_records", 0):
        return (
            f"Pipeline berhasil memproses {extracted_records} transaksi penjualan."
            f"{product_context} Sebanyak {report['loaded_records']} fact ditulis ke warehouse."
        )
    return (
        f"Pipeline memproses {extracted_records} transaksi penjualan, tetapi tidak ada fact yang ditulis ke warehouse."
        f"{product_context}"
    )
