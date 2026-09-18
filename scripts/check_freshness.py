"""Fail when an expected source file is missing or older than MAX_SOURCE_AGE_HOURS."""
from datetime import datetime, timezone
from pathlib import Path
import os
import sys


ROOT = Path(__file__).resolve().parents[1]
SOURCES = ("product.csv", "shopee.csv", "tokopedia.csv", "website.csv", "offline.csv")
max_age = float(os.getenv("MAX_SOURCE_AGE_HOURS", "48"))
now = datetime.now(timezone.utc).timestamp()
stale = []
for name in SOURCES:
    path = ROOT / "data" / "source" / name
    if not path.exists():
        stale.append({"file": name, "reason": "missing"})
        continue
    age_hours = (now - path.stat().st_mtime) / 3600
    if age_hours > max_age:
        stale.append({"file": name, "reason": "stale", "age_hours": round(age_hours, 2)})
print({"checked_at": datetime.now(timezone.utc).isoformat(), "max_age_hours": max_age, "stale": stale})
if stale:
    sys.exit(1)
