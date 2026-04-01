# tests/test_cli.py
"""Tests for CLI commands."""

import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta

import pytest
from click.testing import CliRunner

from gdrive_backup.cli import main, _write_backup_log
from gdrive_backup.sync_engine import DryRunSource, DryRunReport, SyncStats, FolderStats, FileTypeStats, FailureRecord


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
    @patch("gdrive_backup.cli._print_completion_summary")
    def test_run_command_executes_sync(self, mock_summary, mock_logging, mock_load_cfg, mock_build, runner, tmp_path):
        mock_config = MagicMock()
        mock_load_cfg.return_value = mock_config

        mock_engine = MagicMock()
        mock_stats = SyncStats(added=1)
        mock_engine.run.return_value = mock_stats
        mock_build.return_value = mock_engine

        result = runner.invoke(main, ["run", "--config", str(tmp_path / "config.yaml")])
        assert result.exit_code == 0
        mock_build.assert_called_once_with(mock_config, quiet=False)
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


def test_init_github_prompts_saved_to_config(tmp_path):
    """GitHub prompts during init are written to config file."""
    runner = CliRunner()
    input_lines = "\n".join([
        "oauth",           # auth method
        "",                # credentials file (default)
        str(tmp_path / "repo"),   # git repo path
        str(tmp_path / "mirror"), # mirror path
        "y",               # enable github
        "",                # PAT (blank = use env var)
        "alice",           # owner
        "my-backup",       # repo
        "y",               # private
        "y",               # auto_create
        "",                # extra trailing newline for input()
    ])
    result = runner.invoke(
        main, ["init", "--config", str(tmp_path / "config.yaml")],
        input=input_lines,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    config_text = (tmp_path / "config.yaml").read_text()
    assert "github" in config_text
    assert "alice" in config_text
    assert "my-backup" in config_text


def test_init_github_skipped_when_declined(tmp_path):
    """Saying 'n' to GitHub skips the github section."""
    runner = CliRunner()
    input_lines = "\n".join([
        "oauth", "", str(tmp_path / "repo"), str(tmp_path / "mirror"), "n",
    ])
    result = runner.invoke(
        main, ["init", "--config", str(tmp_path / "config.yaml")],
        input=input_lines,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    config_text = (tmp_path / "config.yaml").read_text()
    assert "github:" not in config_text


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


def test_run_pushes_to_github_when_enabled(tmp_path, fake_config_file):
    """After engine.run(), pushes to GitHub when github.enabled."""
    runner = CliRunner()
    from gdrive_backup.sync_engine import SyncStats
    github_cfg = MagicMock(
        enabled=True, owner="alice", repo="backup",
        e2e_output_mode=None, pat="", e2e_base_repo=None,
    )
    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine, \
         patch("gdrive_backup.cli.GithubManager") as mock_gh_cls, \
         patch.dict("os.environ", {"GITHUB_PAT": "test_pat"}):
        cfg = MagicMock(
            github=github_cfg, log_dir=tmp_path,
            log_max_size_mb=10, log_max_files=5, log_default_level="info",
        )
        mock_cfg.return_value = cfg
        engine = MagicMock()
        engine.run.return_value = SyncStats(added=2)
        mock_engine.return_value = engine
        gh_instance = MagicMock()
        gh_instance.get_authenticated_remote_url.return_value = "https://x-access-token:test_pat@github.com/alice/backup.git"
        gh_instance.get_public_remote_url.return_value = "https://github.com/alice/backup.git"
        mock_gh_cls.return_value = gh_instance
        result = runner.invoke(main, ["run", "--config", str(fake_config_file)])
    assert result.exit_code == 0
    gh_instance.validate_pat.assert_called_once()
    gh_instance.ensure_repo_exists.assert_called_once()
    engine.git_manager.push.assert_called_once()
    engine.git_manager.remove_remote.assert_called_once_with("origin")


def test_run_github_push_failure_is_nonfatal(tmp_path, fake_config_file):
    """Push failure does not change exit code to non-zero."""
    from gdrive_backup.sync_engine import SyncStats
    from gdrive_backup.git_manager import GitError
    runner = CliRunner()
    github_cfg = MagicMock(enabled=True, owner="alice", repo="backup",
                           e2e_output_mode=None, pat="tok", e2e_base_repo=None)
    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine, \
         patch("gdrive_backup.cli.GithubManager") as mock_gh_cls:
        mock_cfg.return_value = MagicMock(
            github=github_cfg, log_dir=tmp_path,
            log_max_size_mb=10, log_max_files=5, log_default_level="info",
        )
        engine = MagicMock()
        engine.run.return_value = SyncStats(added=1)
        engine.git_manager.push.side_effect = GitError("network error")
        mock_engine.return_value = engine
        gh_instance = MagicMock()
        gh_instance.get_authenticated_remote_url.return_value = "https://x-access-token:tok@github.com/alice/backup.git"
        mock_gh_cls.return_value = gh_instance
        result = runner.invoke(main, ["run", "--config", str(fake_config_file)])
    assert result.exit_code == 0  # non-fatal
    engine.git_manager.remove_remote.assert_called_once_with("origin")  # cleanup always runs


def test_write_backup_log_creates_file(tmp_path):
    """First run creates the log file with one entry."""
    stats = SyncStats(added=5, failed=1)
    stats.total_files = 10
    stats.end_time = stats.start_time
    stats.record_failure("bad.pdf", "f1", "Docs", "permission_denied", "403")
    stats.record_file("Photos", ".jpg", 5000, 4800)

    _write_backup_log(stats, tmp_path, "full_scan")

    log_path = tmp_path / ".gdrive-backup" / "backup-log.json"
    assert log_path.exists()
    import json as _json
    data = _json.loads(log_path.read_text())
    assert len(data) == 1
    assert data[0]["summary"]["added"] == 5
    assert data[0]["mode"] == "full_scan"
    assert len(data[0]["failures"]) == 1
    assert ".jpg" in data[0]["file_types"]


def test_write_backup_log_appends(tmp_path):
    """Subsequent runs append to the existing log."""
    import json as _json
    log_dir = tmp_path / ".gdrive-backup"
    log_dir.mkdir()
    log_path = log_dir / "backup-log.json"
    log_path.write_text(_json.dumps([{"existing": True}]))

    stats = SyncStats(added=1)
    stats.total_files = 1
    stats.end_time = stats.start_time

    _write_backup_log(stats, tmp_path, "incremental")

    data = _json.loads(log_path.read_text())
    assert len(data) == 2
    assert data[0]["existing"] is True
    assert data[1]["summary"]["added"] == 1


def test_run_prints_rich_summary(tmp_path, fake_config_file):
    """After backup, CLI prints detailed summary with types and folders."""
    runner = CliRunner()
    stats = SyncStats(added=100, failed=2)
    stats.total_files = 110
    stats.drive_total_bytes = 1_000_000_000
    stats.local_total_bytes = 950_000_000
    stats.end_time = stats.start_time + timedelta(minutes=4, seconds=32)
    stats.folders["My Drive/Photos"] = FolderStats(file_count=80, drive_size_bytes=800_000_000, local_size_bytes=760_000_000)
    stats.folders["My Drive/Docs"] = FolderStats(file_count=20, drive_size_bytes=200_000_000, local_size_bytes=190_000_000)
    stats.file_types[".jpg"] = FileTypeStats(count=70, drive_bytes=700_000_000, local_bytes=660_000_000)
    stats.file_types[".pdf"] = FileTypeStats(count=30, drive_bytes=300_000_000, local_bytes=290_000_000)
    stats.record_failure("big.mp4", "f1", "Videos", "too_large", "exceeds limit")
    stats.record_failure("secret.docx", "f2", "Work", "permission_denied", "403")

    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine, \
         patch("gdrive_backup.cli.setup_logging"):
        mock_cfg.return_value = MagicMock(
            github=None, log_dir=tmp_path, log_max_size_mb=10,
            log_max_files=5, log_default_level="info",
            git_repo_path=tmp_path / "repo",
        )
        engine = MagicMock()
        engine.run.return_value = stats
        mock_engine.return_value = engine
        result = runner.invoke(main, ["run", "--config", str(fake_config_file)])

    assert "4m 32s" in result.output
    assert ".jpg" in result.output
    assert ".pdf" in result.output
    assert "My Drive/Photos" in result.output
    assert "Too large" in result.output or "too_large" in result.output
    assert "Permission denied" in result.output or "permission_denied" in result.output


def test_init_shows_gcp_instructions(tmp_path):
    """Init command shows GCP setup instructions."""
    runner = CliRunner()
    input_lines = "\n".join([
        "oauth",
        str(tmp_path / "creds.json"),
        str(tmp_path / "repo"),
        str(tmp_path / "mirror"),
        "n",
    ])
    result = runner.invoke(
        main, ["init", "--config", str(tmp_path / "config.yaml")],
        input=input_lines,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Google Cloud Console" in result.output or "Google Drive API" in result.output


def test_init_validates_credentials_json(tmp_path):
    """Init validates the credentials file is a Desktop app credential."""
    web_cred = tmp_path / "web_creds.json"
    web_cred.write_text(json.dumps({"web": {"client_id": "test"}}))

    valid_cred = tmp_path / "valid_creds.json"
    valid_cred.write_text(json.dumps({"installed": {"client_id": "test"}}))

    runner = CliRunner()
    input_lines = "\n".join([
        "oauth",
        str(web_cred),
        str(valid_cred),
        str(tmp_path / "repo"),
        str(tmp_path / "mirror"),
        "n",
    ])
    result = runner.invoke(
        main, ["init", "--config", str(tmp_path / "config.yaml")],
        input=input_lines,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert (tmp_path / "config.yaml").exists()
