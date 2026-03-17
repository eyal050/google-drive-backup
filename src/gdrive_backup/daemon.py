# src/gdrive_backup/daemon.py
"""Daemon mode — run backups on a polling interval."""

import logging
import os
import signal
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class DaemonError(Exception):
    """Raised when daemon operations fail."""


class Daemon:
    """Runs the sync engine on a polling interval."""

    def __init__(
        self,
        engine,
        poll_interval: int = 300,
        pid_file: Optional[Path] = None,
        max_iterations: Optional[int] = None,
    ):
        self._engine = engine
        self._poll_interval = poll_interval
        self._pid_file = pid_file
        self._max_iterations = max_iterations  # For testing; None = infinite
        self._shutdown = False

    def run(self) -> None:
        """Start the daemon loop."""
        if self._pid_file:
            self._check_and_write_pid()

        self._register_signals()

        try:
            logger.info(f"Daemon started (poll interval: {self._poll_interval}s)")
            iterations = 0

            while not self._shutdown:
                if self._max_iterations is not None and iterations >= self._max_iterations:
                    break

                try:
                    logger.info("Starting backup cycle...")
                    stats = self._engine.run()
                    logger.info(f"Backup cycle complete: {stats.summary()}")
                except Exception as e:
                    logger.error(f"Backup cycle failed: {e}")

                iterations += 1

                if self._max_iterations is not None and iterations >= self._max_iterations:
                    break

                # Sleep with shutdown check
                self._interruptible_sleep(self._poll_interval)

        finally:
            if self._pid_file and self._pid_file.exists():
                self._pid_file.unlink()
                logger.debug("PID file removed")

        logger.info("Daemon stopped")

    def _check_and_write_pid(self) -> None:
        """Check for existing PID file and write current PID."""
        if self._pid_file.exists():
            try:
                existing_pid = int(self._pid_file.read_text().strip())
                # Check if process is still running
                os.kill(existing_pid, 0)
                raise DaemonError(
                    f"Daemon already running (PID {existing_pid}). "
                    f"Remove {self._pid_file} if this is incorrect."
                )
            except ProcessLookupError:
                logger.warning(f"Stale PID file found (PID {existing_pid}), overwriting")
            except ValueError:
                logger.warning("Invalid PID file, overwriting")

        self._pid_file.write_text(str(os.getpid()))
        logger.debug(f"PID file written: {self._pid_file}")

    def _register_signals(self) -> None:
        """Register signal handlers for graceful shutdown."""
        def handler(signum, frame):
            sig_name = signal.Signals(signum).name
            logger.info(f"Received {sig_name}, shutting down gracefully...")
            self._shutdown = True

        signal.signal(signal.SIGTERM, handler)
        signal.signal(signal.SIGINT, handler)

    def _interruptible_sleep(self, seconds: float) -> None:
        """Sleep that can be interrupted by shutdown signal."""
        end_time = time.monotonic() + seconds
        while time.monotonic() < end_time and not self._shutdown:
            time.sleep(min(1.0, end_time - time.monotonic()))
