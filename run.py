"""
ORVIA — Web Server Entry Point
Run this file to start the ORVIA web interface.

Usage:
    python run.py              # Development server
    python run.py --port 8080  # Custom port
    python main.py             # CLI foundation check (Phase 1)
"""
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
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    setup_logging(level="DEBUG" if args.debug else "INFO")
    logger = logging.getLogger("orvia.run")

    config = Config.from_env()
    if args.debug:
        config = Config(
            app_name=config.APP_NAME,
            version=config.VERSION,
            database_path=config.DATABASE_PATH,
            log_level="DEBUG",
            debug=True,
        )
    config.ensure_directories()

    app = create_app(config)

    logger.info("=" * 60)
    logger.info("  ORVIA v%s — Personal Research Intelligence Workspace", config.VERSION)
    logger.info("  Starting web server at http://%s:%d", args.host, args.port)
    logger.info("=" * 60)

    app.run(
        host=args.host,
        port=args.port,
        debug=config.DEBUG,
        use_reloader=config.DEBUG,
    )


if __name__ == "__main__":
    main()
