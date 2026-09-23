"""Single entry point for the Arunika test suite.

Examples:
    python tests/main.py
    python tests/main.py --integration
    python tests/main.py --browser
    python tests/main.py --full

The default is safe for a developer machine: static checks plus every
non-integration pytest test. PostgreSQL acceptance tests are opt-in because
they use Docker and a dedicated ecommerce_sales_test database.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]


def run_step(label: str, command: list[str]) -> None:
    """Print a clear boundary and stop immediately when a check fails."""
    print(f"\n{'=' * 72}\n{label}\n{'=' * 72}")
    subprocess.run(command, cwd=ROOT, check=True)


def require(executable: str, feature: str) -> None:
    if not shutil.which(executable):
        raise SystemExit(f"{feature} requires {executable} on PATH.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--integration",
        action="store_true",
        help="Run the isolated PostgreSQL acceptance test through Docker Compose.",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Run the dashboard browser smoke test with local fixture data.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Run unit/static checks, Docker PostgreSQL acceptance, and browser smoke test.",
    )
    parser.add_argument(
        "--skip-static",
        action="store_true",
        help="Skip SQL and clean-export contract checks; useful while debugging one pytest failure.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    integration = args.integration or args.full
    browser = args.browser or args.full

    if not args.skip_static:
        run_step("SQL safety validation", [sys.executable, "scripts/validate_sql.py"])
        run_step("Clean export contract", [sys.executable, "scripts/check_clean_contract.py"])

    # Do not rely on the skip marker: a misconfigured local environment must
    # not accidentally point the real runner at a developer database.
    # A unique directory below the user profile avoids both an inaccessible
    # Windows Temp folder and OneDrive synchronization in the workspace.
    pytest_temp_root = Path(os.getenv("ARUNIKA_PYTEST_TEMP_ROOT", Path.home() / ".arunika-pytest"))
    pytest_temp_root.mkdir(parents=True, exist_ok=True)
    pytest_temp_base = pytest_temp_root / uuid4().hex
    run_step(
        "Python unit and application tests",
        [
            sys.executable,
            "-m",
            "pytest",
            "tests",
            "-q",
            "-m",
            "not integration",
            f"--basetemp={pytest_temp_base}",
        ],
    )

    if integration:
        require("docker", "PostgreSQL integration test")
        run_step(
            "PostgreSQL end-to-end acceptance test (isolated Docker database)",
            [
                "docker",
                "compose",
                "--profile",
                "test",
                "up",
                "--build",
                "--abort-on-container-exit",
                "--exit-code-from",
                "integration-tests",
                "integration-tests",
            ],
        )

    if browser:
        require("node", "Dashboard browser smoke test")
        run_step("Dashboard browser smoke test (local fixture data)", ["node", "dashboard/tests/browser_smoke.mjs"])

    print("\nPASS: selected test suite completed.")
    if not integration:
        print("Note: PostgreSQL acceptance was not run. Add --integration or use --full.")
    if not browser:
        print("Note: browser smoke test was not run. Add --browser or use --full.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
