"""Tes untuk dashboard."""

import csv
from contextlib import nullcontext
from dataclasses import replace
from io import BytesIO, StringIO

import pytest

from dashboard import app as dashboard_app
from dashboard import routes as dashboard_routes
from dashboard.services import ingestion as dashboard_ingestion
from pipeline.execution import PipelineBusyError
from pipeline.validation.contracts import RAW_COLUMNS, required_raw_columns


def test_order_promotion_is_no_longer_an_upload_source():
    assert "order_promotions" not in dashboard_ingestion.SOURCE_FILES
    assert "order_promotions" not in dashboard_ingestion.SOURCE_COLUMNS


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


@pytest.mark.parametrize("source", ["promo_master", "returns"])
def test_append_csv_batch_supports_auxiliary_sources(tmp_path, monkeypatch, source):
    fields = list(dashboard_ingestion.SOURCE_COLUMNS[source])
    target = tmp_path / dashboard_ingestion.SOURCE_FILES[source]
    target.write_text(",".join(fields) + "\n", encoding="utf-8")
    monkeypatch.setattr(dashboard_ingestion, "SOURCE_DIR", tmp_path)
    row = dict.fromkeys(fields, "fixture")
    payload = StringIO()
    writer = csv.DictWriter(payload, fieldnames=fields)
    writer.writeheader()
    writer.writerow(row)

    assert dashboard_ingestion.append_csv_batch(source, payload.getvalue().encode()) == 1
    with target.open(newline="", encoding="utf-8") as file:
        rows = list(csv.DictReader(file))
    assert rows == [row]


def test_upload_endpoint_requires_admin_token(monkeypatch):
    monkeypatch.setattr(dashboard_app, "settings", replace(dashboard_app.settings, dashboard_admin_token="token"))
    client = dashboard_app.app.test_client()
    response = client.post(
        "/api/ingestion/upload",
        data={"source": "shopee", "file": (BytesIO(b"x"), "batch.csv")},
        content_type="multipart/form-data",
    )
    assert response.status_code == 401


def test_failed_replace_preserves_source(tmp_path, monkeypatch):
    fields = list(RAW_COLUMNS["shopee"])
    required = list(required_raw_columns("shopee"))
    original = (",".join(required) + "\n" + ",".join(["original"] * len(required)) + "\n").encode()
    target = tmp_path / "shopee.csv"
    target.write_bytes(original)
    monkeypatch.setattr(dashboard_ingestion, "SOURCE_DIR", tmp_path)

    def locked(*args):
        raise PermissionError("berkas terkunci")

    monkeypatch.setattr(dashboard_ingestion.os, "replace", locked)
    with pytest.raises(PermissionError):
        dashboard_ingestion.append_csv_batch("shopee", _csv_bytes("shopee", [dict.fromkeys(fields, "new")]))
    assert target.read_bytes() == original
    assert not list(tmp_path.glob("*.tmp"))


@pytest.mark.parametrize("failure,status", [(PermissionError("locked"), 503), (OSError("disk failure"), 500)])
def test_upload_storage_errors_return_json(monkeypatch, failure, status):
    monkeypatch.setattr(dashboard_routes, "settings", replace(dashboard_routes.settings, dashboard_admin_token="test-token"))
    monkeypatch.setattr(dashboard_routes, "pipeline_lock", lambda engine: nullcontext())

    def fail_upload(*args, **kwargs):
        raise failure

    monkeypatch.setattr(dashboard_routes, "append_csv_batch", fail_upload)
    response = dashboard_app.app.test_client().post(
        "/api/ingestion/upload",
        headers={"X-Admin-Token": "test-token"},
        data={"source": "returns", "file": (BytesIO(b"header\nrow\n"), "return_refund.csv")},
    )
    assert response.status_code == status
    assert response.is_json
    assert response.get_json()["error"]


@pytest.mark.parametrize("source", list(dashboard_ingestion.SOURCE_FILES))
def test_explicit_correction_replaces_key_and_preserves_other_rows(tmp_path, monkeypatch, source):
    columns = list(dashboard_ingestion.SOURCE_COLUMNS[source])
    rows = [dict.fromkeys(columns, "1"), dict.fromkeys(columns, "2")]
    target = tmp_path / dashboard_ingestion.SOURCE_FILES[source]
    def payload(records):
        output = StringIO()
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(records)
        return output.getvalue().encode()
    target.write_bytes(payload(rows))
    monkeypatch.setattr(dashboard_ingestion, "SOURCE_DIR", tmp_path)
    changed = dict(rows[0])
    # Kolom terakhir bukan business key untuk seluruh kontrak sumber.
    changed[columns[-1]] = "updated"
    assert dashboard_ingestion.append_csv_batch(source, payload([changed]), mode="correct") == 1
    with target.open(newline="", encoding="utf-8") as file:
        actual = list(csv.DictReader(file))
    assert actual == [rows[1], changed]
    original = target.read_bytes()
    with pytest.raises(ValueError, match="belum ada"):
        dashboard_ingestion.append_csv_batch(source, payload([dict.fromkeys(columns, "3")]), mode="correct")
    assert target.read_bytes() == original


@pytest.mark.parametrize("source", list(dashboard_ingestion.SOURCE_FILES))
def test_upload_endpoint_appends_without_replacing_file(tmp_path, monkeypatch, source):
    columns = list(dashboard_ingestion.SOURCE_COLUMNS[source])
    target = tmp_path / dashboard_ingestion.SOURCE_FILES[source]
    original = (",".join(columns) + "\n" + ",".join(["old"] * len(columns))).encode()
    target.write_bytes(original)  # Uji sumber yang tidak diakhiri newline.
    monkeypatch.setattr(dashboard_ingestion, "SOURCE_DIR", tmp_path)
    monkeypatch.setattr(dashboard_routes, "settings", replace(dashboard_routes.settings, dashboard_admin_token="test-token"))
    monkeypatch.setattr(dashboard_routes, "pipeline_lock", lambda engine: nullcontext())

    def replacement_denied(*args):
        raise PermissionError("penggantian berkas tidak diizinkan")

    monkeypatch.setattr(dashboard_ingestion.os, "replace", replacement_denied)
    payload = (",".join(columns) + "\n" + ",".join(["new"] * len(columns)) + "\n").encode()
    response = dashboard_app.app.test_client().post(
        "/api/ingestion/upload", headers={"X-Admin-Token": "test-token"},
        data={"source": source, "file": (BytesIO(payload), "batch.csv")},
    )
    assert response.status_code == 201
    assert response.get_json()["rows_appended"] == 1
    assert target.read_bytes().startswith(original)
    with target.open(newline="", encoding="utf-8") as file:
        assert list(csv.DictReader(file)) == [dict.fromkeys(columns, "old"), dict.fromkeys(columns, "new")]


def test_failed_append_restores_original_bytes(tmp_path, monkeypatch):
    columns = list(RAW_COLUMNS["shopee"])
    target = tmp_path / "shopee.csv"
    original = _csv_bytes("shopee", [dict.fromkeys(columns, "old")])
    target.write_bytes(original)
    monkeypatch.setattr(dashboard_ingestion, "SOURCE_DIR", tmp_path)
    real_fsync = dashboard_ingestion.os.fsync
    calls = []

    def fail_first_sync(fd):
        calls.append(fd)
        if len(calls) == 1:
            raise OSError("penyimpanan batch gagal")
        return real_fsync(fd)

    monkeypatch.setattr(dashboard_ingestion.os, "fsync", fail_first_sync)
    with pytest.raises(OSError):
        dashboard_ingestion.append_csv_batch("shopee", _csv_bytes("shopee", [dict.fromkeys(columns, "new")]))
    assert target.read_bytes() == original


def test_upload_rejects_when_pipeline_busy(monkeypatch):
    monkeypatch.setattr(dashboard_routes, "settings", replace(dashboard_routes.settings, dashboard_admin_token="test-token"))

    def busy(engine):
        raise PipelineBusyError("busy")

    monkeypatch.setattr(dashboard_routes, "pipeline_lock", busy)
    response = dashboard_app.app.test_client().post(
        "/api/ingestion/upload", headers={"X-Admin-Token": "test-token"},
        data={"source": "returns", "file": (BytesIO(b"header\nrow\n"), "return_refund.csv")},
    )
    assert response.status_code == 409
    assert response.is_json
