"""Application entry point for the Arunika sales dashboard."""

from __future__ import annotations

import sys
import time
from pathlib import Path

if __package__ is None:
    sys.path.insert(0, str(Path.cwd()))

from flask import Flask, request
from sqlalchemy import create_engine

from dashboard.routes import dashboard_routes
from pipeline.config import settings
from pipeline.logger import get_logger

LOGGER = get_logger("dashboard")


def create_app() -> Flask:
    """Create the web application and register its HTTP routes."""
    app = Flask(__name__, template_folder="templates", static_folder="static")
    app.config["TEMPLATES_AUTO_RELOAD"] = True
    app.extensions["warehouse_engine"] = create_engine(
        settings.sqlalchemy_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_timeout=15,
        connect_args={
            "connect_timeout": 10,
            "options": f"-c statement_timeout=30000 -c timezone={settings.app_timezone}",
        },
    )

    @app.context_processor
    def template_helpers():
        static_root = Path(app.static_folder).resolve()

        def asset_version(filename: str) -> str:
            candidate = (static_root / filename).resolve()
            try:
                candidate.relative_to(static_root)
                return str(candidate.stat().st_mtime_ns)
            except (OSError, ValueError):
                return "1"

        return {"asset_version": asset_version}

    @app.before_request
    def start_request_timer():
        request._arunika_started = time.perf_counter()

    @app.after_request
    def log_request(response):
        started = getattr(request, "_arunika_started", None)
        duration_ms = round((time.perf_counter() - started) * 1000, 2) if started else None
        LOGGER.info(
            "dashboard_request",
            extra={
                "request_method": request.method,
                "request_path": request.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
            },
        )
        return response

    app.register_blueprint(dashboard_routes)
    return app


app = create_app()


if __name__ == "__main__":
    if settings.flask_debug:
        app.run(host="127.0.0.1", port=8501, debug=True, use_reloader=False)
    else:
        from waitress import serve

        serve(app, host="0.0.0.0", port=8501, expose_tracebacks=False)
