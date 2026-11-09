"""Tes untuk dashboard."""

import csv
from dataclasses import replace
from io import BytesIO, StringIO

import pytest

from dashboard import app as dashboard_app
from dashboard.services import ingestion as dashboard_ingestion
from pipeline.validation.contracts import RAW_COLUMNS, required_raw_columns


def _csv_bytes(source: str, rows: list[dict]) -> bytes:
    output = StringIO()
    fields = list(RAW_COLUMNS[source])
    writer = csv.DictWriter(output, fieldnames=fields)
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode()


def test_append_csv_batch_validates_contract_and_appends(tmp_path, monkeypatch):
    source = "shopee"
    fields = list(RAW_COLUMNS[source])
    target = tmp_path / "shopee.csv"
    target.write_text(",".join(fields) + "\n", encoding="utf-8")
    monkeypatch.setattr(dashboard_ingestion, "SOURCE_DIR", tmp_path)

    row = dict.fromkeys(fields, "value")
    assert dashboard_ingestion.append_csv_batch(source, _csv_bytes(source, [row])) == 1
    assert len(list(csv.DictReader(target.open(encoding="utf-8", newline="")))) == 1


def test_append_csv_batch_rejects_bad_header(tmp_path, monkeypatch):
    (tmp_path / "shopee.csv").write_text("order_id\n", encoding="utf-8")
    monkeypatch.setattr(dashboard_ingestion, "SOURCE_DIR", tmp_path)
    with pytest.raises(ValueError, match="Header shopee.csv"):
        dashboard_ingestion.append_csv_batch("shopee", b"wrong_header\nvalue\n")


def test_append_csv_batch_upgrades_legacy_header_without_losing_rows(tmp_path, monkeypatch):
    source = "shopee"
    required = list(required_raw_columns(source))
    expected = list(RAW_COLUMNS[source])
    target = tmp_path / "shopee.csv"
    old = dict.fromkeys(required, "old-value")
    with target.open("w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=required)
        writer.writeheader()
        writer.writerow(old)
    monkeypatch.setattr(dashboard_ingestion, "SOURCE_DIR", tmp_path)

    new = dict.fromkeys(expected, "new-value")
    assert dashboard_ingestion.append_csv_batch(source, _csv_bytes(source, [new])) == 1
    with target.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        rows = list(reader)

    assert reader.fieldnames == expected
    assert rows[0]["order_id"] == "old-value"
    assert rows[0]["discount_amount"] == ""
    assert rows[1]["order_id"] == "new-value"
    assert rows[1]["discount_amount"] == "new-value"


def test_upload_endpoint_requires_admin_token(monkeypatch):
    monkeypatch.setattr(dashboard_app, "settings", replace(dashboard_app.settings, dashboard_admin_token="token"))
    client = dashboard_app.app.test_client()
    response = client.post(
        "/api/ingestion/upload",
        data={"source": "shopee", "file": (BytesIO(b"x"), "batch.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 401
