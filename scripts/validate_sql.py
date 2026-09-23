"""SQL safety gate; --database executes all scripts in an isolated PostgreSQL."""

import argparse
import os
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_DIRS = [ROOT / "database/schema", ROOT / "database/views"]


def validate_database(files):
    from sqlalchemy.engine import make_url

    url = make_url(os.environ.get("DATABASE_URL", ""))
    if os.getenv("ARUNIKA_ISOLATED_TEST_DATABASE") != "1" or url.database != "ecommerce_sales_test":
        raise ValueError("--database requires the explicitly isolated ecommerce_sales_test database")
    executable = shutil.which("psql")
    if not executable:
        raise ValueError("psql is required for --database; install the PostgreSQL client")
    environment = dict(
        os.environ,
        PGHOST=url.host or "localhost",
        PGPORT=str(url.port or 5432),
        PGDATABASE=url.database,
        PGUSER=url.username or "",
        PGPASSWORD=url.password or "",
    )
    for file in files:
        # psql handles DO blocks and the bootstrap's conditional \\gexec.
        subprocess.run(
            [executable, "-X", "--no-password", "--set", "ON_ERROR_STOP=1", "--file", str(file)],
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", action="store_true")
    args = parser.parse_args()
    files = sorted(p for directory in SQL_DIRS for p in directory.glob("*.sql"))
    errors = []
    if not files:
        errors.append("No SQL scripts found")
    for path in files:
        sql = path.read_text(encoding="utf-8")
        if re.search(r"\bDROP\s+DATABASE\b", sql, re.I):
            errors.append(f"{path.name}: DROP DATABASE dilarang")
    if errors:
        print("\n".join(errors))
        return 1
    if args.database:
        try:
            validate_database(files)
        except subprocess.CalledProcessError as error:
            print("PostgreSQL SQL validation FAILED:", error.stderr)
            return 1
        except ValueError as error:
            print(error)
            return 1
        print(f"PostgreSQL execution validation OK ({len(files)} files)")
    else:
        print(
            f"SQL safety check OK ({len(files)} files); syntax/schema execution NOT tested. Use --database in isolated tests."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
