"""Verify the requested user-facing schema and safe consolidated exports."""
from decimal import Decimal
from hashlib import sha256

import pandas as pd

from pipeline.validation.analysis import (
    ROOT, SALES_COLUMNS, PRODUCT_COLUMNS, load_analysis, standard_data, export_analysis,
)


def test_all_sales_sources_have_exact_requested_columns_and_types():
    results = load_analysis()
    for name, result in results.items():
        data = standard_data({name: result})
        if name == 'product':
            assert list(data) == PRODUCT_COLUMNS
            continue
        assert list(data) == SALES_COLUMNS
        assert 'customer_id' not in data.columns
        assert str(data.quantity.dtype) == 'Int64'
        assert pd.api.types.is_datetime64_any_dtype(data.tanggal_order)
        assert data.harga_satuan.map(lambda x: isinstance(x, Decimal)).all()
        assert (data.total_harga == data.quantity * data.harga_satuan).all()
        assert not data.duplicated(['channel', 'order_id']).any()
        assert data.product_id.isin(results['product'].clean.sku).all()
        assert data.status.isin(['Completed', 'Cancelled', 'Returned']).all()
    website = standard_data({'website': results['website']})
    assert website.kota.isna().all()
    offline = standard_data({'offline': results['offline']})
    assert offline.kota.tolist() == results['offline'].clean.store_city.tolist()


def test_exports_have_one_schema_and_single_source_does_not_replace_overview(tmp_path):
    results = load_analysis()
    export_analysis(results, tmp_path)
    report = (tmp_path / 'summary.csv').read_bytes()
    for source in ['shopee', 'tokopedia', 'website', 'offline', 'sales']:
        data = pd.read_csv(tmp_path / f'{source}.csv', dtype='string')
        assert list(data) == SALES_COLUMNS
        assert data.tanggal_order.str.fullmatch(r'\d{4}-\d{2}-\d{2}').all()
    export_analysis({'shopee': results['shopee']}, tmp_path)
    assert report == (tmp_path / 'summary.csv').read_bytes()
    issues = pd.read_csv(tmp_path / 'quality_issues.csv')
    assert {'raw_payload', 'source_row_number', 'source_sha256', 'rule'} <= set(issues)


def test_notebook_cells_run_without_changing_sources(monkeypatch, tmp_path):
    import contextlib
    import io
    import json
    import pipeline.validation.analysis as helpers

    # Exercise every code cell while redirecting only exports to a temporary folder.
    original_export = helpers.export_analysis
    monkeypatch.setattr(helpers, 'export_analysis', lambda results: original_export(results, tmp_path))
    paths = list((ROOT / 'data/source').glob('*.csv'))
    before = {p: sha256(p.read_bytes()).hexdigest() for p in paths}
    for cwd in [ROOT, ROOT / 'analisis']:
        monkeypatch.chdir(cwd)
        for path in (ROOT / 'analisis').glob('*.ipynb'):
            nb = json.loads(path.read_text(encoding='utf-8'))
            headings = [''.join(c['source']) for c in nb['cells'] if c['cell_type'] == 'markdown']
            for number, label in enumerate(['Missing value', 'Duplicate', 'Invalid value',
                                            'Date format', 'Data type', 'Product consistency'], 1):
                assert any(h.startswith(f'## {number}. {label}') for h in headings)
            namespace = {'__name__': '__main__'}
            with contextlib.redirect_stdout(io.StringIO()):
                for cell in nb['cells']:
                    if cell['cell_type'] == 'code':
                        exec(compile(''.join(cell['source']), str(path), 'exec'), namespace)
    assert before == {p: sha256(p.read_bytes()).hexdigest() for p in paths}
