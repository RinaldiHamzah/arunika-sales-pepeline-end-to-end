import pytest

from pipeline.returns import extract_return_events, normalize_return_record


def _return(**overrides):
    row = {
        "source_name": "SHOPEE",
        "return_id": "RET-SHP-0001",
        "return_line_number": "1",
        "order_id": "SHP-0001",
        "order_line_number": "2",
        "return_date": "2026-08-10",
        "return_reason": "Produk rusak saat diterima",
        "return_status": "approved",
        "quantity_returned": "1",
        "refund_amount": "",
        "refund_status": "pending",
    }
    row.update(overrides)
    return row


def test_return_row_is_normalized_and_keeps_order_line_reference():
    row = normalize_return_record(_return(source_name=" offline ", order_id=" POS-0301 "))

    assert row["source_name"] == "OFFLINE_STORE"
    assert row["source_order_id"] == "POS-0301"
    assert row["source_line_number"] == 2
    assert row["return_status"] == "APPROVED"
    assert row["refund_status"] == "PENDING"
    assert row["refund_amount"] is None


def test_processed_refund_requires_a_nonnegative_amount():
    row = normalize_return_record(
        _return(return_status="processed", refund_status="processed", refund_amount="12000.00")
    )

    assert str(row["refund_amount"]) == "12000.00"
    with pytest.raises(ValueError, match="tidak boleh negatif"):
        normalize_return_record(_return(return_status="processed", refund_status="processed", refund_amount="-1"))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"return_date": "27/07/2026"}, "YYYY-MM-DD"),
        ({"quantity_returned": "0"}, "bilangan bulat positif"),
        ({"refund_status": "processed"}, "wajib diisi"),
        ({"return_status": "pending", "refund_status": "processed", "refund_amount": "1"}, "tidak dapat"),
        (
            {"refund_status": "processed", "return_status": "approved", "refund_amount": "100000000000000"},
            "NUMERIC\\(16,2\\)",
        ),
    ],
)
def test_invalid_return_rows_are_rejected_by_contract(changes, message):
    with pytest.raises(ValueError, match=message):
        normalize_return_record(_return(**changes))


def test_missing_returns_file_is_treated_as_empty_optional_source(tmp_path):
    source = extract_return_events(tmp_path)

    assert source.source_name == "RETURN_EVENTS"
    assert source.frame.empty
    assert source.source_records == 0


def test_returns_csv_requires_the_documented_header(tmp_path):
    (tmp_path / "returns.csv").write_text("return_id,order_id\nRET-1,ORD-1\n", encoding="utf-8")

    with pytest.raises(ValueError, match="header harus persis"):
        extract_return_events(tmp_path)
