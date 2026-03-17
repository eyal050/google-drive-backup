# tests/test_cli.py
"""Tests for CLI commands."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from gdrive_backup.cli import main


class TestCLI:
    @pytest.fixture
    def runner(self):
        return CliRunner()

    def test_help_shows_commands(self, runner):
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "init" in result.output
        assert "run" in result.output
        assert "daemon" in result.output
        assert "status" in result.output

    @patch("gdrive_backup.cli._build_engine")
    @patch("gdrive_backup.cli.load_config")
    @patch("gdrive_backup.cli.setup_logging")
    def test_run_command_executes_sync(self, mock_logging, mock_load_cfg, mock_build, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config

        mock_engine = MagicMock()
        mock_stats = MagicMock()
        mock_stats.summary.return_value = "1 added"
        mock_stats.failed = 0
        mock_engine.run.return_value = mock_stats
        mock_build.return_value = mock_engine

        result = runner.invoke(main, ["run", "--config", str(tmp_path / "config.yaml")])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(mock_config)
        mock_engine.run.assert_called_once()

    def test_run_with_missing_config_fails(self, runner):
        result = runner.invoke(main, ["run", "--config", "/nonexistent/config.yaml"])
        assert result.exit_code != 0

    @patch("gdrive_backup.cli.load_config")
    @patch("gdrive_backup.cli._load_state_file")
    def test_status_command(self, mock_load_state, mock_load_cfg, runner, tmp_path):
        mock_config = MagicMock()
        mock_config.state_file = tmp_path / "state.json"
        mock_load_cfg.return_value = mock_config
        mock_load_state.return_value = {
            "last_run": "2026-03-17T14:30:00Z",
            "last_run_status": "success",
            "file_cache": {"f1": {}, "f2": {}},
            "start_page_token": "12345",
        }
        result = runner.invoke(main, ["status", "--config", str(tmp_path / "c.yaml")])
        assert "success" in result.output
        assert "2" in result.output  # 2 files tracked
