"""Simple, shared notebook interface using the user's 12-column sales format."""
from pathlib import Path

import pandas as pd

from pipeline.validation.contracts import CHANNEL_LABELS, CLEAN_PRODUCT_COLUMNS, CLEAN_SALES_COLUMNS
from pipeline.validation.data_quality import ROOT, SPECS, analyze, run_quality

SALES_COLUMNS = list(CLEAN_SALES_COLUMNS)
PRODUCT_COLUMNS = list(CLEAN_PRODUCT_COLUMNS)
CHANNELS = dict(CHANNEL_LABELS)
CHECKS = {
    'missing': {'MISSING_REQUIRED', 'MISSING_OPTIONAL'},
    'duplicate': {'DUPLICATE_BUSINESS_KEY', 'CONFLICTING_DUPLICATE'},
    'invalid': {'INVALID_NUMBER', 'NON_POSITIVE', 'INVALID_INTEGER',
                'INVALID_MONEY_PRECISION_OR_RANGE', 'AMOUNT_MISMATCH', 'INVALID_STATUS',
                'PRICE_DIFFERS_FROM_MASTER', 'INVALID_EMAIL', 'UNKNOWN_PAYMENT'},
    'date': {'INVALID_DATE'},
    'product': {'UNMAPPED_PRODUCT'},
}


def validate_sales_contract(data: pd.DataFrame) -> pd.DataFrame:
    """Fail fast when a clean transaction export drifts from its public contract."""
    if list(data.columns) != SALES_COLUMNS:
        raise ValueError(f'Clean sales schema must be exactly: {SALES_COLUMNS}')
    if 'customer_id' in data.columns:
        raise ValueError('customer_id is not part of the clean sales contract')
    if data['order_id'].isna().any() or data['product_id'].isna().any():
        raise ValueError('Clean sales requires non-null order_id and product_id')
    if not pd.api.types.is_datetime64_any_dtype(data['tanggal_order']):
        raise TypeError('tanggal_order must be datetime64 before CSV export')
    if str(data['quantity'].dtype) != 'Int64':
        raise TypeError('quantity must use nullable integer (Int64) dtype')
    return data


def load_analysis(source='all', source_dir=None):
    folder = Path(source_dir) if source_dir else ROOT / 'data/source'
    if source == 'all':
        return run_quality(folder)
    if source not in {'product', *SPECS}:
        raise ValueError(f'Unknown source: {source}')
    master = analyze(folder / 'product.csv', 'product')
    if source == 'product':
        return {'product': master}
    return {source: analyze(folder / f'{source}.csv', source, master.clean)}


def standard_data(results):
    """Keep typed dates/money and exactly one user-facing schema across channels."""
    if set(results) == {'product'}:
        return results['product'].clean.rename(columns={
            'sku': 'product_id', 'category': 'kategori', 'price': 'harga_satuan',
        })[PRODUCT_COLUMNS].copy()
    parts = []
    for source, result in results.items():
        if source == 'product':
            continue
        data = result.clean.rename(columns={
            'sku': 'product_id', 'category': 'kategori', 'gross_amount': 'total_harga',
            'order_date': 'tanggal_order', 'unit_price': 'harga_satuan',
        }).copy()
        data['kota'] = data['store_city'] if source == 'offline' else data['customer_city']
        data['channel'] = pd.Series(CHANNELS[source], index=data.index, dtype='string')
        data['status'] = data['status'].str.title()
        parts.append(data[SALES_COLUMNS])
    return validate_sales_contract(pd.concat(parts, ignore_index=True))


def quality_issues(results, check=None):
    issues = pd.concat([r.issues for r in results.values()], ignore_index=True)
    if check is not None:
        issues = issues[issues['rule'].isin(CHECKS[check])]
    issues = issues[~issues['field'].astype(str).str.lower().eq('customer_id')]
    return issues.rename(columns={
        'source': 'sumber', 'source_row_number': 'baris', 'severity': 'tingkat',
        'field': 'kolom', 'rule': 'masalah', 'raw_value': 'nilai_asli',
    })[['sumber', 'baris', 'tingkat', 'kolom', 'masalah', 'nilai_asli']].reset_index(drop=True)


def missing_values(results):
    parts = []
    for source, result in results.items():
        profile = result.profile[['column', 'missing_count']].copy()
        profile.insert(0, 'sumber', source)
        parts.append(profile)
    missing = pd.concat(parts, ignore_index=True).rename(columns={
        'column': 'kolom', 'missing_count': 'jumlah_kosong'})
    return missing[~missing['kolom'].astype(str).str.lower().eq('customer_id')].reset_index(drop=True)


def type_report(data):
    records = []
    for col in data:
        nonmissing = data[col].dropna()
        value_type = type(nonmissing.iloc[0]).__name__ if len(nonmissing) else 'kosong'
        records.append({'kolom': col, 'dtype': str(data[col].dtype), 'tipe_nilai': value_type})
    return pd.DataFrame(records)


def summary(results):
    return pd.DataFrame([r.summary for r in results.values()]).rename(columns={
        'source': 'sumber', 'extracted_records': 'awal', 'valid_records': 'bersih',
        'duplicate_records': 'duplikat', 'invalid_records': 'ditolak',
    })[['sumber', 'awal', 'bersih', 'duplikat', 'ditolak']]


def export_analysis(results, output_dir=None):
    target = Path(output_dir) if output_dir else ROOT / 'data/processed/clean'
    original = (ROOT / 'data/source').resolve()
    resolved = target.resolve()
    if original == resolved or original in resolved.parents or resolved in original.parents:
        raise ValueError('Output must not overlap source directory')
    # Build and validate every export before overwriting an existing clean file.
    exports = {source: standard_data({source: result}) for source, result in results.items()}
    combined = standard_data(results) if set(results) == {'product', *SPECS} else None
    target.mkdir(parents=True, exist_ok=True)
    for source, result in results.items():
        exports[source].to_csv(target / f'{source}.csv', index=False, date_format='%Y-%m-%d')
    # Only the overview writes shared reports, preventing a single-source notebook
    # from replacing the consolidated report with a partial one.
    if set(results) == {'product', *SPECS}:
        combined.to_csv(target / 'sales.csv', index=False, date_format='%Y-%m-%d')
        summary(results).to_csv(target / 'summary.csv', index=False)
        # Keep detailed evidence out of the displayed sales dataset.
        evidence = []
        for source, result in results.items():
            issues = result.issues.copy()
            payloads = pd.concat([result.rejected, result.duplicates], ignore_index=True)
            issues = issues.merge(payloads[['source_row_number', 'raw_payload']],
                                  on='source_row_number', how='left', validate='many_to_one')
            evidence.append(issues)
        pd.concat(evidence, ignore_index=True).to_csv(target / 'quality_issues.csv', index=False)
    return target


if __name__ == '__main__':
    results = load_analysis()
    print(summary(results).to_string(index=False))
    print('Hasil:', export_analysis(results))
