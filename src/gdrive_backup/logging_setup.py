# src/gdrive_backup/logging_setup.py
"""Configure rotating file and console logging."""

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path


LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)-5s %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(
    log_dir: Path,
    max_size_mb: int = 10,
    max_files: int = 5,
    default_level: str = "info",
    console_level: str | None = None,
) -> None:
    """Configure logging with rotating file handler and console handler.

    Args:
        log_dir: Directory for log files.
        max_size_mb: Max size per log file in MB before rotation.
        max_files: Number of rotated log files to keep.
        default_level: Default log level for file handler.
        console_level: Override log level for console. None = same as default.
            Use "WARNING" for --quiet, "DEBUG" for --debug.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "gdrive-backup.log"

    root_logger = logging.getLogger("gdrive_backup")
    root_logger.setLevel(logging.DEBUG)  # Capture everything, filter at handlers

    # Clear existing handlers (for re-init safety)
    root_logger.handlers.clear()

    # File handler — rotating
    file_handler = RotatingFileHandler(
        log_file,
        maxBytes=max_size_mb * 1024 * 1024,
        backupCount=max_files,
    )
    file_handler.setLevel(getattr(logging, default_level.upper()))
    file_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    root_logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stderr)
    effective_console_level = console_level or default_level
    console_handler.setLevel(getattr(logging, effective_console_level.upper()))
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=LOG_DATE_FORMAT))
    root_logger.addHandler(console_handler)
