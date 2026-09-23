"""One reporting vocabulary for the runner, dashboard and daily email."""


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


def outcome_message(report):
    if report.get("status") == "FAILED":
        return "Pipeline gagal. Lihat alasan kegagalan; data belum tentu sudah divalidasi."
    if report.get("source_records") is None:
        return "Run lama: jumlah data yang dilewati sebelum validasi belum direkam."
    if report.get("extracted_records", 0) == 0:
        return "Tidak ada kandidat baru/berubah. Baris identik dilewati sebelum validasi, bukan divalidasi ulang."
    if report.get("loaded_records", 0):
        return "Fact berhasil ditulis (insert atau koreksi). Periksa juga jumlah data ditolak dan duplikat validasi."
    return "Tidak ada fact ditulis. Kandidat sudah identik dengan warehouse, ditolak, atau terdeteksi duplikat saat validasi."
