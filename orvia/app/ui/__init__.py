"""
ORVIA UI Package
Flask application factory for the ORVIA web interface.
"""
from __future__ import annotations

import logging
from pathlib import Path

from flask import Flask, current_app, g

from orvia.app.core.config import Config
from orvia.app.core.database import DatabaseManager

logger = logging.getLogger(__name__)


def get_db() -> DatabaseManager:
    """Get or create a thread-local DatabaseManager for the active request context."""
    if "db" not in g:
        config: Config = current_app.config["ORVIA_CONFIG"]
        db = DatabaseManager(config.DATABASE_PATH)
        db.connect()
        g.db = db
    return g.db


def create_app(config: Config | None = None) -> Flask:
    """Create and configure the Flask application."""
    if config is None:
        config = Config.from_env()
        config.ensure_directories()

    app = Flask(
        __name__,
        template_folder="templates",
        static_folder="static",
        static_url_path="/static",
    )

    app.config.update(
        SECRET_KEY="orvia-dev-secret-change-in-production",
        ORVIA_CONFIG=config,
        DEBUG=config.DEBUG,
    )

    # ── Initialize Database Schema ────────────────────────────────────────────
    init_db = DatabaseManager(config.DATABASE_PATH)
    init_db.connect()
    init_db.initialize_schema()
    init_db.disconnect()
    logger.info("ORVIA UI: database schema verified at %s", config.DATABASE_PATH)

    # ── Blueprints / Routes ───────────────────────────────────────────────────
    from orvia.app.ui.routes import register_routes  # noqa: PLC0415

    register_routes(app)

    # ── Jinja2 Filters ────────────────────────────────────────────────────────
    import datetime as _dt

    @app.template_filter("datefmt")
    def _datefmt_filter(value: object, fmt: str = "%Y-%m-%d") -> str:
        """
        Safely format a date/datetime value to a string.

        Accepts:
          - datetime.datetime or datetime.date objects  → strftime(fmt)
          - ISO-8601 strings                            → parse then strftime
          - None / empty string                         → ''
        """
        if not value:
            return ""
        if isinstance(value, (_dt.datetime, _dt.date)):
            return value.strftime(fmt)
        if isinstance(value, str):
            try:
                return _dt.datetime.fromisoformat(value).strftime(fmt)
            except ValueError:
                # Return the raw string sliced as a best-effort fallback
                return value[:10] if len(value) >= 10 else value
        return str(value)

    # ── Global Jinja2 context ─────────────────────────────────────────────────
    @app.context_processor
    def inject_globals() -> dict:
        return {
            "app_name": "ORVIA",
            "app_version": config.VERSION,
            "app_tagline": "Explore Information. Discover What Connects.",
        }

    # ── Teardown ──────────────────────────────────────────────────────────────
    @app.teardown_appcontext
    def close_db(exc: BaseException | None = None) -> None:  # noqa: ARG001
        db: DatabaseManager | None = g.pop("db", None)
        if db is not None:
            try:
                db.disconnect()
            except Exception:  # noqa: BLE001
                pass

    return app
