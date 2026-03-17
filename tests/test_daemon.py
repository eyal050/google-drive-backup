# tests/test_daemon.py
"""Tests for daemon mode."""

import signal
import os
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest

from gdrive_backup.daemon import Daemon, DaemonError


class TestDaemon:
    @pytest.fixture
    def mock_engine(self):
        engine = MagicMock()
        stats = MagicMock()
        stats.summary.return_value = "1 added"
        stats.failed = 0
        engine.run.return_value = stats
        return engine

    @pytest.fixture
    def pid_file(self, tmp_path):
        return tmp_path / "daemon.pid"

    def test_creates_pid_file(self, mock_engine, pid_file):
        daemon = Daemon(mock_engine, poll_interval=1, pid_file=pid_file, max_iterations=1)
        daemon.run()
        # PID file should be cleaned up after exit
        assert not pid_file.exists()

    def test_prevents_duplicate_instance(self, mock_engine, pid_file):
        pid_file.write_text(str(os.getpid()))  # Write current PID (still running)
        daemon = Daemon(mock_engine, poll_interval=1, pid_file=pid_file)
        with pytest.raises(DaemonError, match="already running"):
            daemon.run()

    def test_stale_pid_file_is_overwritten(self, mock_engine, pid_file):
        pid_file.write_text("99999999")  # Non-existent PID
        daemon = Daemon(mock_engine, poll_interval=1, pid_file=pid_file, max_iterations=1)
        daemon.run()  # Should not raise

    def test_runs_sync_on_interval(self, mock_engine, pid_file):
        daemon = Daemon(mock_engine, poll_interval=0.1, pid_file=pid_file, max_iterations=3)
        daemon.run()
        assert mock_engine.run.call_count == 3

    def test_continues_after_sync_error(self, mock_engine, pid_file):
        mock_engine.run.side_effect = [Exception("oops"), MagicMock(summary=lambda: "ok", failed=0)]
        daemon = Daemon(mock_engine, poll_interval=0.1, pid_file=pid_file, max_iterations=2)
        daemon.run()
        assert mock_engine.run.call_count == 2

    def test_graceful_shutdown(self, mock_engine, pid_file):
        daemon = Daemon(mock_engine, poll_interval=10, pid_file=pid_file)
        daemon._shutdown = True  # Simulate signal
        daemon.run()
        # Should exit immediately
