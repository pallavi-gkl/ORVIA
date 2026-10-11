"""
ORVIA — Web Server Entry Point
Run this file to start the ORVIA web interface.

Usage:
    python run.py              # Development server
    python run.py --port 8080  # Custom port
    python main.py             # CLI foundation check (Phase 1)
"""
import os
import sys
import argparse
import logging
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).parent))

from orvia.app.core.config import Config
from orvia.app.core.logging_config import setup_logging
from orvia.app.ui import create_app


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ORVIA — Personal Research Intelligence Workspace",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default=None,
        help="Host to bind (default: 127.0.0.1 locally, 0.0.0.0 on Render or when PORT/HOST is set)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Port to bind (default: 5000 locally, $PORT on Render)",
    )
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    config = Config.from_env()

    # Detect deployment environment: Render provides PORT and sets RENDER=true
    is_deployed = bool(os.environ.get("RENDER")) or bool(os.environ.get("PORT"))

    # Resolve host: CLI argument > Config (which evaluates ORVIA_HOST/HOST/Render 0.0.0.0 / local 127.0.0.1)
    host = args.host or config.HOST

    # Resolve port: CLI argument > Config (which evaluates PORT/ORVIA_PORT / local 5000)
    port = args.port or config.PORT

    # Resolve debug mode: disabled in deployment unless explicitly requested via CLI
    if args.debug:
        debug_mode = True
    elif is_deployed:
        debug_mode = False
    else:
        debug_mode = config.DEBUG

    if debug_mode != config.DEBUG or host != config.HOST or port != config.PORT:
        config = Config(
            app_name=config.APP_NAME,
            version=config.VERSION,
            database_path=config.DATABASE_PATH,
            log_level="DEBUG" if debug_mode else config.LOG_LEVEL,
            debug=debug_mode,
            host=host,
            port=port,
        )

    setup_logging(level="DEBUG" if config.DEBUG else "INFO")
    logger = logging.getLogger("orvia.run")

    config.ensure_directories()

    app = create_app(config)

    logger.info("=" * 60)
    logger.info("  ORVIA v%s — Personal Research Intelligence Workspace", config.VERSION)
    logger.info("  Starting web server at http://%s:%d", host, port)
    logger.info(
        "  Environment: %s",
        "Render / Cloud Deployment" if is_deployed else "Local Development",
    )
    logger.info("  Debug mode: %s", "ENABLED" if config.DEBUG else "DISABLED")
    logger.info("=" * 60)

    app.run(
        host=host,
        port=port,
        debug=config.DEBUG,
        use_reloader=config.DEBUG,
    )


if __name__ == "__main__":
    main()
