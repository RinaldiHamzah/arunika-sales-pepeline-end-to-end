"""Reproducible file-based DQ used by all analysis notebooks.

Run: python -m pipeline.validation.data_quality
Source files are never modified. Money stays Decimal until CSV serialization.
"""

import argparse
import csv
import io
import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path

import pandas as pd

from pipeline.validation.contracts import (
    INTERNAL_SALES_COLUMNS,
    META_COLUMNS,
    PRODUCT_RAW_COLUMNS,
    SOURCE_SPECS,
    VALID_STATUSES,
)
from pipeline.validation.rules import clean_text, match_key, number, parse_date

ROOT = Path(__file__).resolve().parents[2]
SPECS = {source: dict(spec) for source, spec in SOURCE_SPECS.items()}
PRODUCT_COLUMNS = list(PRODUCT_RAW_COLUMNS)
META = list(META_COLUMNS)
SALES_COLUMNS = list(INTERNAL_SALES_COLUMNS)
PAYMENTS = {match_key(v): v for v in ["Transfer Bank", "E-Wallet", "Credit Card", "COD", "Cash"]}
CITIES = {
    match_key(v): v
    for v in ["Jakarta", "Bandung", "Surabaya", "Yogyakarta", "Semarang", "Medan", "Makassar", "Denpasar"]
}


@dataclass
class QualityResult:
    clean: pd.DataFrame
    rejected: pd.DataFrame
    duplicates: pd.DataFrame
    issues: pd.DataFrame
    profile: pd.DataFrame
    summary: dict


def read_source(path, payload=None):
    """Hash exactly the bytes parsed; preserve strings, empty cells, and identifiers."""
    payload = path.read_bytes() if payload is None else payload
    reader = csv.reader(io.StringIO(payload.decode("utf-8-sig"), newline=""))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError(f"{path.name}: empty file without header") from exc
    if len(set(header)) != len(header):
        raise ValueError(f"{path.name}: duplicate column names")
    rows = list(reader)
    if any(len(row) != len(header) for row in rows):
        raise ValueError(f"{path.name}: malformed CSV row width")
    return pd.DataFrame(rows, columns=header, dtype="string"), sha256(payload).hexdigest()


def frame(rows, columns):
    result = pd.DataFrame(rows, columns=columns)
    for col in ["quantity", "line_number", "source_row_number"]:
        if col in result:
            result[col] = result[col].astype("Int64")
    if "order_date" in result:
        result["order_date"] = pd.to_datetime(result["order_date"])
    for col in result:
        if col not in {
            "quantity",
            "line_number",
            "source_row_number",
            "order_date",
            "price",
            "unit_price",
            "gross_amount",
            "source_total_amount",
        }:
            result[col] = result[col].astype("string")
    return result


def analyze(path, source, products=None, selected_row_numbers=None, captured=None):
    path = Path(path)
    data, checksum = read_source(path) if captured is None else captured
    expected = PRODUCT_COLUMNS if source == "product" else list(SPECS[source].values())
    missing = sorted(set(expected) - set(data.columns))
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}")
    if selected_row_numbers is not None:
        selected = {int(row_number) for row_number in selected_row_numbers}
        data = data.iloc[[index for index in range(len(data)) if index + 1 in selected]].copy()
    profile = pd.DataFrame(
        [
            {
                "column": col,
                "raw_dtype": str(data[col].dtype),
                "missing_count": sum(clean_text(v) is None for v in data[col]),
                "distinct_nonmissing": len({clean_text(v) for v in data[col]} - {None}),
            }
            for col in data
        ]
    )
    lookup = {}
    if source != "product":
        if products is None or products.empty:
            raise ValueError("A nonempty validated Product Master is required")
        for prod in products.to_dict("records"):
            for key in [match_key(prod["sku"]), match_key(prod["product_name"])]:
                if key in lookup and lookup[key]["sku"] != prod["sku"]:
                    raise ValueError(f"Ambiguous Product Master mapping: {key}")
                lookup[key] = prod
    issues, candidates = [], []
    for source_row_number, raw in zip(data.index + 1, data.to_dict("records")):
        meta = dict(
            source=source, source_file=path.name, source_row_number=int(source_row_number), source_sha256=checksum
        )
        errors = []

        def issue(code, field, severity="ERROR"):
            issues.append({**meta, "severity": severity, "rule": code, "field": field, "raw_value": raw.get(field)})
            if severity == "ERROR":
                errors.append(f"{field}:{code}")

        if source == "product":
            row = {key: clean_text(raw[key]) for key in PRODUCT_COLUMNS}
            for key in PRODUCT_COLUMNS[:-1]:
                if row[key] is None:
                    issue("MISSING_REQUIRED", key)
            row["sku"] = row["sku"].upper() if row["sku"] else None
            row["price"], err = number(raw["price"])
            if err:
                issue(err, "price")
            key = row["sku"]
        else:
            mapping = SPECS[source]
            row = {col: None for col in SALES_COLUMNS}
            row.update({key: clean_text(raw[col]) for key, col in mapping.items()})
            row["line_number"] = 1
            if not row["order_id"]:
                issue("MISSING_REQUIRED", mapping["order_id"])
            row["order_date"], err = parse_date(row["order_date"], source)
            if err:
                issue(err, mapping["order_date"])
            for col in ["quantity", "unit_price"]:
                row[col], err = number(row[col], integer=col == "quantity")
                if err:
                    issue(err, mapping[col])
            status = (row["status"] or "").upper()
            if not status:
                issue("MISSING_REQUIRED", mapping["status"])
            elif status not in VALID_STATUSES:
                issue("INVALID_STATUS", mapping["status"])
            row["status"] = status
            product = lookup.get(match_key(row["product_input"]))
            if row["product_input"] is None:
                issue("MISSING_REQUIRED", mapping["product_input"])
            elif product is None:
                issue("UNMAPPED_PRODUCT", mapping["product_input"])
            else:
                row.update({k: product[k] for k in ["sku", "product_name", "brand", "category"]})
                if row["unit_price"] is not None and row["unit_price"] != product["price"]:
                    issue("PRICE_DIFFERS_FROM_MASTER", mapping["unit_price"], "WARNING")
            row.pop("product_input", None)
            if row["quantity"] is not None and row["unit_price"] is not None:
                row["gross_amount"] = row["quantity"] * row["unit_price"]
            if "source_total_amount" in mapping:
                row["source_total_amount"], err = number(row["source_total_amount"])
                if err:
                    issue(err, mapping["source_total_amount"])
                elif row["gross_amount"] is not None and row["source_total_amount"] != row["gross_amount"]:
                    issue("AMOUNT_MISMATCH", mapping["source_total_amount"])
            for col in [
                "customer_name",
                "customer_email",
                "customer_city",
                "store_name",
                "store_city",
                "payment_method",
            ]:
                if col in mapping and row[col] is None:
                    issue("MISSING_OPTIONAL", mapping[col], "WARNING")
            for col in ["customer_city", "store_city"]:
                if row[col]:
                    row[col] = CITIES.get(match_key(row[col]), row[col])
            if row["payment_method"]:
                payment = PAYMENTS.get(match_key(row["payment_method"]))
                if payment is None:
                    issue("UNKNOWN_PAYMENT", mapping["payment_method"], "WARNING")
                else:
                    row["payment_method"] = payment
            if row["customer_email"]:
                if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", row["customer_email"]):
                    issue("INVALID_EMAIL", mapping["customer_email"], "WARNING")
                    row["customer_email"] = None
            key = row["order_id"]
        row.update(meta)
        candidates.append({"row": row, "errors": errors, "raw": raw, "key": key})

    # Conflicting versions of the same key are all quarantined. No arbitrary winner.
    groups = {}
    for candidate in candidates:
        if candidate["key"]:
            groups.setdefault(candidate["key"], []).append(candidate)
    conflicts = set()
    for key, group in groups.items():
        signatures = {
            json.dumps({k: v for k, v in item["row"].items() if k not in META}, sort_keys=True, default=str)
            for item in group
        }
        if len(signatures) > 1:
            conflicts.add(key)

    clean, rejected, duplicates, seen = [], [], [], set()
    for candidate in candidates:
        row, errors, key = candidate["row"], candidate["errors"], candidate["key"]
        meta = {k: row[k] for k in META}
        if key in conflicts:
            errors.append("business_key:CONFLICTING_DUPLICATE")
            issues.append(
                {
                    **meta,
                    "severity": "ERROR",
                    "rule": "CONFLICTING_DUPLICATE",
                    "field": "business_key",
                    "raw_value": key,
                }
            )
        record = {
            **meta,
            "business_key": key,
            "reasons": "|".join(errors),
            "raw_payload": json.dumps(candidate["raw"], ensure_ascii=False),
        }
        if errors:
            rejected.append(record)
        elif key in seen:
            record["reasons"] = "DUPLICATE_BUSINESS_KEY"
            duplicates.append(record)
            issues.append(
                {
                    **meta,
                    "severity": "INFO",
                    "rule": "DUPLICATE_BUSINESS_KEY",
                    "field": "business_key",
                    "raw_value": key,
                }
            )
        else:
            seen.add(key)
            clean.append(row)
    columns = PRODUCT_COLUMNS + META if source == "product" else SALES_COLUMNS
    evidence_cols = META + ["business_key", "reasons", "raw_payload"]
    summary = dict(
        source=source,
        source_sha256=checksum,
        extracted_records=len(data),
        valid_records=len(clean),
        duplicate_records=len(duplicates),
        invalid_records=len(rejected),
        warning_count=sum(i["severity"] == "WARNING" for i in issues),
    )
    assert len(data) == len(clean) + len(duplicates) + len(rejected)
    return QualityResult(
        frame(clean, columns),
        pd.DataFrame(rejected, columns=evidence_cols),
        pd.DataFrame(duplicates, columns=evidence_cols),
        pd.DataFrame(issues, columns=META + ["severity", "rule", "field", "raw_value"]),
        profile,
        summary,
    )


def run_quality(source_dir=None, output_dir=None, selected_row_numbers=None, captured_sources=None):
    """Explicit source allowlist; never accidentally ingest old exports or copies."""
    source_dir = Path(source_dir) if source_dir else ROOT / "data/source"
    captured = captured_sources or {}
    results = {"product": analyze(source_dir / "product.csv", "product", captured=captured.get("product"))}
    for source in SPECS:
        selected_rows = (selected_row_numbers or {}).get(source)
        results[source] = analyze(
            source_dir / f"{source}.csv", source, results["product"].clean, selected_rows, captured.get(source)
        )
    if output_dir is not None:
        target = Path(output_dir).resolve()
        original = source_dir.resolve()
        if target == original or original in target.parents or target in original.parents:
            raise ValueError("Output directory must not overlap source directory")
        target.mkdir(parents=True, exist_ok=True)
        for source, result in results.items():
            for label in ["clean", "rejected", "duplicates", "issues", "profile"]:
                getattr(result, label).to_csv(target / f"{source}_{label}.csv", index=False, date_format="%Y-%m-%d")
        pd.DataFrame([r.summary for r in results.values()]).to_csv(target / "summary.csv", index=False)
        pd.concat([results[s].clean for s in SPECS], ignore_index=True).to_csv(
            target / "sales_clean.csv", index=False, date_format="%Y-%m-%d"
        )
        manifest = {
            "policy_version": "1.0",
            "source_files": [r.summary for r in results.values()],
            "money": "IDR Decimal, two decimal places",
            "date": "YYYY-MM-DD, calendar date without timezone",
            "grain": "one line per order; conflicts quarantined; multi-line sources need a line ID",
        }
        (target / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "data/processed/data_quality")
    args = parser.parse_args()
    results = run_quality(output_dir=args.output_dir)
    print(pd.DataFrame([r.summary for r in results.values()]).drop(columns="source_sha256").to_string(index=False))
