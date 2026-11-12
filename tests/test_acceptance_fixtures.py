"""Pastikan batch tes penerimaan lolos validator sebelum pengujian database."""

import shutil

from pipeline.validation.data_quality import analyze
from tests.test_integration_postgres import ROOT, _append_valid_website_rows, _website_order_lines


def test_acceptance_website_batches_pass_quality_validation(tmp_path):
    for name in ("product_master.csv", "website.csv"):
        shutil.copy2(ROOT / "data/source" / name, tmp_path / name)
    products = analyze(tmp_path / "product_master.csv", "product").clean
    before = analyze(tmp_path / "website.csv", "website", products)

    _append_valid_website_rows(tmp_path, 20)
    after = analyze(tmp_path / "website.csv", "website", products)
    assert len(after.clean) == len(before.clean) + 20
    assert len(after.rejected) == len(before.rejected)
    assert len(after.duplicates) == len(before.duplicates)

    order_id = "WEB-ACCEPTANCE-LINES"
    for count, changed_line in ((5, None), (5, 3), (6, 3), (5, None)):
        _website_order_lines(tmp_path, order_id, count, changed_line)
        result = analyze(tmp_path / "website.csv", "website", products)
        lines = result.clean[result.clean.order_id == order_id].sort_values("line_number")
        assert list(lines.line_number) == list(range(1, count + 1))
        assert list(lines.quantity) == [4 if line == changed_line else 1 for line in range(1, count + 1)]
        assert len(result.rejected) == len(before.rejected)
        assert len(result.duplicates) == len(before.duplicates)
