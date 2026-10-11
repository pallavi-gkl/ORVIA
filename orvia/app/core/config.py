"""
Application configuration for ORVIA.
All settings are read from environment variables with sensible defaults.
"""

import os
from pathlib import Path


# The project root is two levels above this file:
# orvia/app/core/config.py  ->  orvia/app/core  ->  orvia/app  ->  project root
_PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]


class Config:
    """
    Central configuration object for ORVIA.

    All settings are sourced from environment variables (prefixed with ORVIA_)
    with safe, documented defaults. Use :meth:`from_env` to obtain an instance.
    """

    def __init__(
        self,
        app_name: str = "ORVIA",
        version: str = "1.0.0",
        database_path: Path | None = None,
        log_level: str = "INFO",
        debug: bool = False,
        host: str | None = None,
        port: int | None = None,
    ) -> None:
        self.APP_NAME: str = app_name
        self.VERSION: str = version
        self.DATABASE_PATH: Path = (
            database_path
            if database_path is not None
            else _PROJECT_ROOT / "data" / "orvia.db"
        )
        self.LOG_LEVEL: str = log_level.upper()
        self.DEBUG: bool = debug
        self.HOST: str = host or "127.0.0.1"
        self.PORT: int = port if port is not None else 5000

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "Config":
        """Construct a Config instance from environment variables."""

        def _bool(value: str) -> bool:
            return value.strip().lower() in {"1", "true", "yes"}

        raw_db_path = os.environ.get("ORVIA_DATABASE_PATH", "")
        database_path: Path | None = None
        if raw_db_path:
            p = Path(raw_db_path)
            database_path = p if p.is_absolute() else _PROJECT_ROOT / p

        # Resolve port: PORT (standard Render/cloud) -> ORVIA_PORT -> 5000
        raw_port = os.environ.get("PORT") or os.environ.get("ORVIA_PORT")
        port = int(raw_port) if raw_port and raw_port.isdigit() else 5000

        # Resolve host: ORVIA_HOST / HOST -> 0.0.0.0 if on Render or PORT present -> 127.0.0.1
        env_host = os.environ.get("ORVIA_HOST") or os.environ.get("HOST")
        if env_host:
            host = env_host
        elif os.environ.get("RENDER") or os.environ.get("PORT"):
            host = "0.0.0.0"
        else:
            host = "127.0.0.1"

        return cls(
            app_name=os.environ.get("ORVIA_APP_NAME", "ORVIA"),
            version=os.environ.get("ORVIA_VERSION", "0.1.0"),
            database_path=database_path,
            log_level=os.environ.get("ORVIA_LOG_LEVEL", "INFO"),
            debug=_bool(os.environ.get("ORVIA_DEBUG", "false")),
            host=host,
            port=port,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def ensure_directories(self) -> None:
        """Create all required application directories (idempotent)."""
        dirs: list[Path] = [
            self.DATABASE_PATH.parent,           # data/
            _PROJECT_ROOT / "data" / "sources",
            _PROJECT_ROOT / "data" / "exports",
            _PROJECT_ROOT / "logs",
            _PROJECT_ROOT / "assets",
            _PROJECT_ROOT / "config",
            _PROJECT_ROOT / "orvia" / "app" / "core",
            _PROJECT_ROOT / "orvia" / "app" / "models",
            _PROJECT_ROOT / "orvia" / "app" / "repositories",
            _PROJECT_ROOT / "orvia" / "app" / "services",
            _PROJECT_ROOT / "orvia" / "app" / "search",
            _PROJECT_ROOT / "orvia" / "app" / "analysis",
            _PROJECT_ROOT / "orvia" / "app" / "ingestion",
            _PROJECT_ROOT / "orvia" / "app" / "reports",
            _PROJECT_ROOT / "orvia" / "app" / "storage",
            _PROJECT_ROOT / "orvia" / "app" / "ui",
        ]
        for directory in dirs:
            directory.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Dunder
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Config("
            f"APP_NAME={self.APP_NAME!r}, "
            f"VERSION={self.VERSION!r}, "
            f"DATABASE_PATH={self.DATABASE_PATH!r}, "
            f"LOG_LEVEL={self.LOG_LEVEL!r}, "
            f"DEBUG={self.DEBUG!r}, "
            f"HOST={self.HOST!r}, "
            f"PORT={self.PORT!r})"
        )
