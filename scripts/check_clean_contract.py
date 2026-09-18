"""Quick contract validation for final clean exports.

Run before publishing a notebook or exporting a final dataset.
"""
from __future__ import annotations

from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CLEAN_DIR = ROOT / "data" / "processed" / "clean"

SALES_COLUMNS = [
    "order_id",
    "product_id",
    "product_name",
    "kategori",
    "quantity",
    "total_harga",
    "tanggal_order",
    "kota",
    "channel",
    "status",
    "customer_email",
    "harga_satuan",
]

PRODUCT_COLUMNS = ["product_id", "product_name", "brand", "kategori", "harga_satuan"]
ALLOWED_STATUS = {"Completed", "Cancelled", "Returned"}


def validate_file(path: Path) -> list[str]:
    problems: list[str] = []
    if not path.exists():
        return [f"Missing file: {path.name}"]

    df = pd.read_csv(path)
    expected = PRODUCT_COLUMNS if path.name == "product.csv" else SALES_COLUMNS

    if "customer_id" in df.columns:
        problems.append(f"{path.name}: customer_id is still present in the clean export")
    if list(df.columns) != expected:
        problems.append(f"{path.name}: expected columns {expected}, found {list(df.columns)}")

    if path.name != "product.csv" and "status" in df.columns:
        bad_status = df.loc[~df["status"].astype(str).isin(ALLOWED_STATUS), "status"]
        if not bad_status.empty:
            problems.append(f"{path.name}: invalid status values found: {bad_status.unique().tolist()}")

    return problems


def main() -> int:
    if not CLEAN_DIR.exists():
        print(f"Clean folder not found: {CLEAN_DIR}")
        return 1

    files = [
        path for path in sorted(CLEAN_DIR.glob("*.csv"))
        if path.name not in {"summary.csv", "quality_issues.csv"}
    ]
    if not files:
        print(f"No clean export CSV files found in {CLEAN_DIR}")
        return 1

    problems: list[str] = []
    for file in files:
        problems.extend(validate_file(file))

    if problems:
        print("Clean contract check FAILED")
        for item in problems:
            print(f"- {item}")
        return 1

    print("Clean contract check OK")
    for file in files:
        print(f"- {file.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
