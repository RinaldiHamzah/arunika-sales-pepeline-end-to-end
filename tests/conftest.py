"""Pytest configuration shared by direct and wrapper-based test runs."""

from __future__ import annotations

import os
from pathlib import Path
from uuid import uuid4

DEFAULT_TEMP_ROOT = Path.home() / ".arunika-pytest"


def pytest_configure(config) -> None:
    """Use a unique user-owned temp directory when pytest is run directly.

    Some Windows installations deny access to the default ``%TEMP%/pytest-*``
    folder, while a folder inside OneDrive can be locked by synchronization.
    The root can be overridden with ``ARUNIKA_PYTEST_TEMP_ROOT`` when needed.
    """
    if config.option.basetemp is None:
        root = Path(os.getenv("ARUNIKA_PYTEST_TEMP_ROOT", DEFAULT_TEMP_ROOT))
        root.mkdir(parents=True, exist_ok=True)
        config.option.basetemp = root / uuid4().hex
