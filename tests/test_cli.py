# tests/test_cli.py
"""Tests for CLI commands."""

from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from click.testing import CliRunner

from gdrive_backup.cli import main
from gdrive_backup.sync_engine import DryRunSource, DryRunReport


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


def _make_dry_run_report():
    return DryRunReport(
        source=DryRunSource.DRIVE_API,
        text_file_count=10,
        binary_file_count=5,
        text_size_bytes=1024 * 1024 * 100,  # 100 MB
        binary_size_bytes=1024 * 1024 * 500,  # 500 MB
        sizes_available=True,
        git_repo_path="/tmp/repo",
        mirror_path="/tmp/mirror",
        auth_method="oauth",
        include_shared=False,
        max_file_size_mb=0,
        github_repo="alice/backup",
    )


def test_dry_run_flag_calls_run_dry(tmp_path, fake_config_file):
    """--dry-run calls engine.run_dry() and prints report."""
    runner = CliRunner()
    report = _make_dry_run_report()
    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine:
        mock_cfg.return_value = MagicMock(
            github=None, log_dir=tmp_path, log_max_size_mb=10,
            log_max_files=5, log_default_level="info",
        )
        engine = MagicMock()
        engine.run_dry.return_value = report
        mock_engine.return_value = engine
        result = runner.invoke(main, ["run", "--dry-run", "--config", str(fake_config_file)])
    assert result.exit_code == 0
    engine.run_dry.assert_called_once()
    engine.run.assert_not_called()
    assert "Dry run" in result.output
    assert "Text files" in result.output
    assert "10" in result.output


def test_dry_run_skips_github_push(tmp_path, fake_config_file):
    """--dry-run never pushes to GitHub even if github.enabled."""
    runner = CliRunner()
    report = _make_dry_run_report()
    github_cfg = MagicMock(enabled=True, pat="tok", owner="alice", repo="backup",
                           e2e_output_mode=None)
    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine, \
         patch("gdrive_backup.cli.GithubManager") as mock_gh:
        mock_cfg.return_value = MagicMock(
            github=github_cfg, log_dir=tmp_path,
            log_max_size_mb=10, log_max_files=5, log_default_level="info",
        )
        engine = MagicMock()
        engine.run_dry.return_value = report
        mock_engine.return_value = engine
        result = runner.invoke(main, ["run", "--dry-run", "--config", str(fake_config_file)])
    assert result.exit_code == 0
    mock_gh.assert_not_called()


def test_dry_run_sizes_unknown_shows_message(tmp_path, fake_config_file):
    """When sizes_available=False, output includes 'size unknown'."""
    runner = CliRunner()
    report = _make_dry_run_report()
    report.sizes_available = False
    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine:
        mock_cfg.return_value = MagicMock(
            github=None, log_dir=tmp_path, log_max_size_mb=10,
            log_max_files=5, log_default_level="info",
        )
        engine = MagicMock()
        engine.run_dry.return_value = report
        mock_engine.return_value = engine
        result = runner.invoke(main, ["run", "--dry-run", "--config", str(fake_config_file)])
    assert "size unknown" in result.output
