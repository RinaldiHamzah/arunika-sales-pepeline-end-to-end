"""Static SQL gate used in CI (no database required)."""
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SQL_DIRS = [ROOT / "database/schema", ROOT / "database/views"]

def main() -> int:
    files = [p for d in SQL_DIRS for p in d.glob("*.sql")]
    errors = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        if re.search(r"\bDROP\s+DATABASE\b", text, re.I):
            errors.append(f"{path}: DROP DATABASE dilarang")
    if errors:
        print("SQL validation FAILED")
        print("\n".join(errors))
        return 1
    print(f"SQL validation OK ({len(files)} files)")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
