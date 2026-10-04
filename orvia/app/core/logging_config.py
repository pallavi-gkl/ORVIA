"""
Logging configuration for ORVIA.
Sets up both console and rotating file handlers with a clean format.
"""

import logging
import logging.handlers
from pathlib import Path


def setup_logging(level: str = "INFO") -> logging.Logger:
    """
    Configure application-wide logging.

    Sets up a console handler and a rotating file handler that writes to
    logs/orvia.log (max 5 MB, 3 backups). Creates the logs/ directory if
    it does not already exist.

    Args:
        level: The minimum logging level string (e.g. 'DEBUG', 'INFO', 'WARNING').

    Returns:
        The configured root Logger instance.
    """
    logs_dir = Path("logs")
    logs_dir.mkdir(parents=True, exist_ok=True)

    log_format = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"
    formatter = logging.Formatter(fmt=log_format, datefmt=date_format)

    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root_logger = logging.getLogger()
    root_logger.setLevel(numeric_level)

    # Avoid duplicate handlers on repeated calls (e.g. during tests)
    if root_logger.handlers:
        root_logger.handlers.clear()

    # --- Console handler ---
    console_handler = logging.StreamHandler()
    console_handler.setLevel(numeric_level)
    console_handler.setFormatter(formatter)
    root_logger.addHandler(console_handler)

    # --- Rotating file handler ---
    file_handler = logging.handlers.RotatingFileHandler(
        filename=logs_dir / "orvia.log",
        maxBytes=5 * 1024 * 1024,  # 5 MB
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setLevel(numeric_level)
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    root_logger.debug("Logging initialised at level '%s'.", level.upper())
    return root_logger
