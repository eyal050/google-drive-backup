# src/gdrive_backup/cli.py
"""CLI entry point for gdrive-backup."""

import glob as _glob
import json
import logging
import os
import readline
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import click
import yaml

from gdrive_backup import __version__
from gdrive_backup.auth import authenticate, build_drive_service, AuthError
from gdrive_backup.classifier import FileClassifier
from gdrive_backup.config import Config, ConfigError, load_config, DEFAULT_CONTROL_DIR
from gdrive_backup.drive_client import DriveClient
from gdrive_backup.git_manager import GitManager, GitError
from gdrive_backup.logging_setup import setup_logging
from gdrive_backup.mirror_manager import MirrorManager
from gdrive_backup.sync_engine import SyncEngine, SyncError, DryRunReport, DryRunSource
from gdrive_backup.github_manager import GithubManager, GithubError

logger = logging.getLogger(__name__)


def _resolve_config_path(config_path: Optional[str]) -> Path:
    if config_path:
        return Path(config_path)
    return DEFAULT_CONTROL_DIR / "config.yaml"


def _resolve_control_dir(config_path: Optional[str]) -> Path:
    if config_path:
        return Path(config_path).parent
    return DEFAULT_CONTROL_DIR


def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def _print_completion_summary(stats, log_path: str = None) -> None:
    """Print a rich backup completion summary."""
    duration = ""
    if stats.end_time and stats.start_time:
        elapsed = (stats.end_time - stats.start_time).total_seconds()
        duration = f" in {_format_duration(elapsed)}"

    click.echo(f"\nBackup complete{duration}\n")
    click.echo(f"  Files: {stats.summary()}")

    if stats.drive_total_bytes > 0 or stats.local_total_bytes > 0:
        click.echo(f"  Storage: {_format_bytes(stats.drive_total_bytes)} on Drive -> {_format_bytes(stats.local_total_bytes)} local")

    if stats.file_types:
        click.echo("\n  By type:")
        sorted_types = sorted(stats.file_types.items(), key=lambda x: x[1].count, reverse=True)
        for ext, ft in sorted_types:
            click.echo(f"    {ext:<25} {ft.count:>6,} files  {_format_bytes(ft.local_bytes):>10}")

    if stats.folders:
        sorted_folders = sorted(stats.folders.items(), key=lambda x: x[1].file_count, reverse=True)
        top = sorted_folders[:10]
        click.echo(f"\n  Top folders ({min(10, len(sorted_folders))}):")
        for path, fs in top:
            display_path = path if path else "(root)"
            click.echo(f"    {display_path:<40} {fs.file_count:>6,} files  {_format_bytes(fs.local_size_bytes):>10}")

    if stats.failures:
        click.echo(f"\n  Failed ({len(stats.failures)} files):")
        by_reason = {}
        for f in stats.failures:
            by_reason.setdefault(f.reason, []).append(f.file_name)
        reason_labels = {
            "too_large": "Too large",
            "permission_denied": "Permission denied",
            "export_failed": "Export failed",
            "disk_full": "Disk full",
            "download_error": "Download error",
            "unknown": "Unknown error",
        }
        for reason, files in by_reason.items():
            label = reason_labels.get(reason, reason)
            names = ", ".join(files[:5])
            if len(files) > 5:
                names += f", ... (+{len(files) - 5} more)"
            click.echo(f"    {label} ({len(files)}): {names}")

    if log_path:
        click.echo(f"\n  Full details: {log_path}")

    click.echo("")


def _write_backup_log(stats, git_repo_path, mode: str) -> None:
    """Append a JSON log entry for this backup run."""
    log_dir = Path(git_repo_path) / ".gdrive-backup"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "backup-log.json"

    duration = 0
    if stats.end_time and stats.start_time:
        duration = (stats.end_time - stats.start_time).total_seconds()

    entry = {
        "timestamp": stats.start_time.isoformat() if stats.start_time else datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 1),
        "mode": mode,
        "total_files_on_drive": stats.total_files,
        "summary": {
            "added": stats.added,
            "modified": stats.modified,
            "deleted": stats.deleted,
            "skipped": stats.skipped,
            "failed": stats.failed,
        },
        "storage": {
            "drive_total_bytes": stats.drive_total_bytes,
            "local_total_bytes": stats.local_total_bytes,
        },
        "file_types": {
            ext: {"count": ft.count, "drive_bytes": ft.drive_bytes, "local_bytes": ft.local_bytes}
            for ext, ft in stats.file_types.items()
        },
        "folders": {
            path: {"file_count": fs.file_count, "drive_bytes": fs.drive_size_bytes, "local_bytes": fs.local_size_bytes}
            for path, fs in stats.folders.items()
        },
        "failures": [
            {
                "file_name": f.file_name,
                "file_id": f.file_id,
                "folder_path": f.folder_path,
                "reason": f.reason,
                "error_message": f.error_message,
            }
            for f in stats.failures
        ],
    }

    existing = []
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text())
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    log_path.write_text(json.dumps(existing, indent=2))
    logger.debug(f"Backup log written to {log_path}")


def _build_engine(config: Config, quiet: bool = False) -> SyncEngine:
    """Build a SyncEngine from a validated config."""
    logger.info("Authenticating with Google Drive API...")
    try:
        creds = authenticate(config.auth_method, config.credentials_file, config.token_file)
    except AuthError as e:
        logger.error(f"Authentication failed: {e}")
        raise

    logger.info("Building Drive API service...")
    try:
        service = build_drive_service(creds)
    except Exception as e:
        logger.error(f"Failed to build Drive API service: {e}")
        raise AuthError(f"Failed to build Drive API service: {e}") from e

    logger.info("Initializing backup components...")
    try:
        drive_client = DriveClient(service)
    except Exception as e:
        logger.error(f"Failed to create Drive client: {e}")
        raise

    try:
        git_manager = GitManager.init_repo(config.git_repo_path)
        logger.info(f"Git repo ready: {config.git_repo_path}")
    except GitError as e:
        logger.error(f"Failed to initialize git repo at {config.git_repo_path}: {e}")
        raise

    try:
        mirror_manager = MirrorManager(config.mirror_path)
        logger.info(f"Mirror directory ready: {config.mirror_path}")
    except Exception as e:
        logger.error(f"Failed to initialize mirror at {config.mirror_path}: {e}")
        raise

    classifier = FileClassifier()

    return SyncEngine(
        drive_client=drive_client,
        git_manager=git_manager,
        mirror_manager=mirror_manager,
        classifier=classifier,
        state_file=config.state_file,
        max_file_size_mb=config.max_file_size_mb,
        include_shared=config.include_shared,
        folder_ids=config.folder_ids,
        quiet=quiet,
    )


def _load_state_file(state_path: Path) -> Optional[dict]:
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Failed to load state file {state_path}: {e}")
            return None
    return None


@click.group()
@click.version_option(version=__version__)
@click.pass_context
def main(ctx):
    """Google Drive Backup — back up your Drive to git + mirror."""
    ctx.ensure_object(dict)


def _enable_readline():
    """Enable readline tab-completion for file paths and input history."""
    def _path_completer(text, state):
        expanded = Path(text).expanduser()
        matches = _glob.glob(str(expanded) + "*")
        matches = [m + "/" if Path(m).is_dir() else m for m in matches]
        if text.startswith("~"):
            home = str(Path.home())
            matches = ["~" + m[len(home):] for m in matches]
        return matches[state] if state < len(matches) else None

    readline.set_completer(_path_completer)
    readline.set_completer_delims(" \t\n")
    if "libedit" in (readline.__doc__ or ""):
        readline.parse_and_bind("bind ^I rl_complete")
    else:
        readline.parse_and_bind("tab: complete")


def _prompt_path(label: str, default: str = "") -> str:
    """Prompt for a path using input() so readline tab-completion and history work."""
    if default:
        readline.set_startup_hook(lambda: readline.insert_text(default))
    try:
        value = input(f"{label}: ").strip() or default
    finally:
        readline.set_startup_hook()
    if value:
        readline.add_history(value)
    return value


def _prompt_text(label: str, default: str = "") -> str:
    """Prompt for text using input() so readline history (up/down arrows) works."""
    suffix = f" [{default}]" if default else ""
    value = input(f"{label}{suffix}: ").strip() or default
    if value:
        readline.add_history(value)
    return value


GCP_INSTRUCTIONS = """
Google Cloud Console Setup
==========================

Before you can use gdrive-backup, you need Google OAuth credentials.
Follow these steps (takes about 2 minutes):

  1. Open the Google Cloud Console and create or select a project:
     https://console.cloud.google.com/

  2. Enable the Google Drive API:
     https://console.cloud.google.com/apis/library/drive.googleapis.com
     -> Click "Enable"

  3. Create OAuth 2.0 credentials:
     https://console.cloud.google.com/apis/credentials
     -> Create Credentials -> OAuth client ID
     -> Application type: Desktop app
     -> Name it anything (e.g. "gdrive-backup")
     -> Click Create, then Download JSON

  4. Note the path to the downloaded file - you will enter it below.

"""


def _validate_credentials_json(path: Path) -> tuple:
    """Validate a Google OAuth Desktop app credentials JSON file."""
    if not path.exists():
        return False, f"File not found: {path}"
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    if "installed" in data:
        return True, ""
    if "web" in data:
        return False, (
            "This is a Web application credential, not a Desktop app credential.\n"
            "  Please create a new OAuth client ID with Application type: Desktop app"
        )
    if data.get("type") == "service_account":
        return False, (
            "This is a service account key, not an OAuth credential.\n"
            "  Select 'service_account' as auth method for service account setup."
        )
    return False, "Unrecognized credentials format. Expected a Desktop app OAuth credential."


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
@click.pass_context
def init(ctx, config_path):
    """Set up a new backup configuration."""
    import shutil

    _enable_readline()
    control_dir = _resolve_control_dir(config_path)
    control_dir.mkdir(parents=True, exist_ok=True)
    (control_dir / "logs").mkdir(exist_ok=True)

    config_file = control_dir / "config.yaml"

    if config_file.exists():
        click.echo(f"Config already exists at {config_file}")
        if not click.confirm("Overwrite?"):
            return

    # Show GCP instructions
    click.echo(GCP_INSTRUCTIONS)

    # Auth method
    auth_method = _prompt_text("Authentication method (oauth/service_account)", "oauth")

    # Credentials file with validation
    creds_path = None
    for attempt in range(3):
        creds_input = _prompt_path(
            "Path to credentials JSON file",
            str(control_dir / "credentials.json"),
        )
        creds_path = Path(creds_input).expanduser()

        if not creds_path.exists():
            click.echo(f"  Note: File not found at {creds_path}. You can place it there later.")
            break

        if auth_method == "oauth":
            ok, error = _validate_credentials_json(creds_path)
            if ok:
                dest = control_dir / "credentials.json"
                if creds_path.resolve() != dest.resolve():
                    shutil.copy2(creds_path, dest)
                    dest.chmod(0o600)
                    click.echo(f"  Credentials copied to {dest}")
                creds_path = dest
                break
            else:
                click.echo(f"  Error: {error}")
                if attempt < 2:
                    click.echo("  Please try again.\n")
        else:
            break
    else:
        click.echo("  Too many failed attempts. You can place the credentials file manually.")
        creds_path = control_dir / "credentials.json"

    # Backup paths
    git_repo_path = _prompt_path("Git repo path (for text files)", str(Path.home() / "gdrive-backup-repo"))
    mirror_path = _prompt_path("Mirror path (for binary files)", str(Path.home() / "gdrive-backup-mirror"))

    # Write config
    config_data = {
        "auth": {
            "method": auth_method,
            "credentials_file": creds_path.name if creds_path.parent == control_dir else str(creds_path),
            "token_file": "token.json",
        },
        "backup": {
            "git_repo_path": git_repo_path,
            "mirror_path": mirror_path,
        },
        "scope": {
            "include_shared": False,
            "folder_ids": [],
        },
        "sync": {
            "state_file": "state.json",
        },
        "max_file_size_mb": 0,
        "logging": {
            "max_size_mb": 10,
            "max_files": 5,
            "default_level": "info",
        },
        "daemon": {
            "poll_interval": 300,
        },
    }

    # GitHub setup
    github_data = None
    if click.confirm("\nEnable GitHub push?", default=False):
        gh_pat = _prompt_text("  GitHub PAT (leave blank to use GITHUB_PAT env var)")

        if gh_pat:
            click.echo("  Validating PAT...")
            try:
                temp_mgr = GithubManager(gh_pat, "test", "test")
                temp_mgr.validate_pat()
                click.echo("  PAT validated successfully.")
            except GithubError as e:
                click.echo(f"  Warning: PAT validation failed: {e}")
                if not click.confirm("  Continue anyway?", default=False):
                    gh_pat = ""

        gh_owner = _prompt_text("  GitHub owner (user or org)")
        gh_repo = _prompt_text("  Repository name", "gdrive-backup-data")
        gh_private = click.confirm("  Private repo?", default=True)
        gh_auto_create = click.confirm("  Auto-create if missing?", default=True)

        github_data = {
            "enabled": True,
            "pat": gh_pat,
            "owner": gh_owner,
            "repo": gh_repo,
            "private": gh_private,
            "auto_create": gh_auto_create,
        }

    if github_data:
        config_data["github"] = github_data

    with open(config_file, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False)
    os.chmod(config_file, 0o600)

    # Initialize git repo
    git_path = Path(git_repo_path).expanduser()
    GitManager.init_repo(git_path)

    # Create mirror directory
    Path(mirror_path).expanduser().mkdir(parents=True, exist_ok=True)

    click.echo(f"\nSetup complete!")
    click.echo(f"  Config: {config_file}")
    click.echo(f"  Git repo: {git_path}")
    click.echo(f"  Mirror: {mirror_path}")
    click.echo(f"\nTo start your first backup, run: gdrive-backup run")


def _resolve_pat(config) -> Optional[str]:
    """Resolve PAT from env var (priority) or config value."""
    return os.environ.get("GITHUB_PAT") or config.github.pat or None


def _resolve_repo_name(config) -> str:
    """Return timestamped name in e2e mode, else config.github.repo."""
    if config.github.e2e_output_mode is not None:
        return datetime.now(timezone.utc).strftime("%d-%m-%Y-%H-%M") + "_gdrive-backup"
    return config.github.repo


def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"


def _print_dry_run_report(report: DryRunReport) -> None:
    size_str = "(size unknown)" if not report.sizes_available else None

    click.echo("Dry run — no files will be written\n")
    click.echo(f"Source:         {report.source.value}")
    text_size = size_str or _format_bytes(report.text_size_bytes)
    bin_size = size_str or _format_bytes(report.binary_size_bytes)
    total_size = size_str or _format_bytes(report.text_size_bytes + report.binary_size_bytes)
    click.echo(f"Text files:     {report.text_file_count:,}  ({text_size})")
    click.echo(f"Binary files:   {report.binary_file_count:,}  ({bin_size})")
    click.echo(f"Total:          {report.text_file_count + report.binary_file_count:,}  ({total_size})")
    click.echo("")
    click.echo(f"Git repo:       {report.git_repo_path}")
    click.echo(f"Mirror:         {report.mirror_path}")
    if report.github_repo:
        click.echo(f"GitHub repo:    {report.github_repo}  (not validated — value from config)")
    click.echo(f"Auth method:    {report.auth_method}")
    click.echo(f"Include shared: {str(report.include_shared).lower()}")
    click.echo(f"Max file size:  {'no limit' if report.max_file_size_mb == 0 else str(report.max_file_size_mb) + ' MB'}")


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
@click.option("-v", "--verbose", is_flag=True, help="Increase log verbosity")
@click.option("--debug", is_flag=True, help="Maximum log verbosity")
@click.option("-q", "--quiet", is_flag=True, help="Suppress console output")
@click.option("-n", "--dry-run", "dry_run", is_flag=True,
              help="Preview what would be backed up without writing anything")
@click.pass_context
def run(ctx, config_path, verbose, debug, quiet, dry_run):
    """Run a single backup."""
    # Determine console log level
    if quiet:
        console_level = "ERROR"
    elif debug:
        console_level = "DEBUG"
    elif verbose:
        console_level = "INFO"
    else:
        console_level = None  # Use config default

    resolved_config_path = _resolve_config_path(config_path)
    control_dir = _resolve_control_dir(config_path)

    try:
        config = load_config(str(resolved_config_path), str(control_dir))
    except ConfigError as e:
        click.echo(f"Config error: {e}", err=True)
        sys.exit(2)

    setup_logging(
        config.log_dir,
        config.log_max_size_mb,
        config.log_max_files,
        config.log_default_level,
        console_level,
    )

    # Log startup information
    logger.info(f"gdrive-backup v{__version__} starting")
    logger.info(f"Config: {resolved_config_path}")
    logger.info(f"Auth method: {config.auth_method}")
    logger.info(f"Git repo: {config.git_repo_path}")
    logger.info(f"Mirror: {config.mirror_path}")
    logger.debug(f"State file: {config.state_file}")
    logger.debug(f"Include shared: {config.include_shared}")
    logger.debug(f"Folder IDs: {config.folder_ids}")
    logger.debug(f"Max file size: {config.max_file_size_mb} MB (0=no limit)")

    try:
        engine = _build_engine(config, quiet=quiet)

        if dry_run:
            github_repo = (
                f"{config.github.owner}/{config.github.repo}"
                if config.github and config.github.enabled
                else None
            )
            try:
                report = engine.run_dry(
                    git_repo_path=str(config.git_repo_path),
                    mirror_path=str(config.mirror_path),
                    auth_method=config.auth_method,
                    max_file_size_mb=config.max_file_size_mb,
                    github_repo=github_repo,
                )
                _print_dry_run_report(report)
            except SyncError as e:
                click.echo(f"Dry run failed: {e}", err=True)
                sys.exit(2)
            return

        logger.info("Starting backup...")
        stats = engine.run()
        logger.info(f"Backup finished: {stats.summary()}")

        # Write JSON backup log
        try:
            mode = "full_scan" if stats.total_files > 0 else "incremental"
            _write_backup_log(stats, config.git_repo_path, mode)
            engine.git_manager.ensure_gitignore(".gdrive-backup/")
        except Exception as e:
            logger.warning(f"Failed to write backup log: {e}")

        # GitHub push (skipped when --dry-run; dry_run branch already returned above)
        if config.github and config.github.enabled:
            pat = _resolve_pat(config)
            if not pat:
                click.echo("GitHub push skipped: no PAT found (set GITHUB_PAT or github.pat in config)", err=True)
            else:
                repo_name = _resolve_repo_name(config)
                remote_branch = repo_name if config.github.e2e_output_mode == "new_branch" else "main"
                logger.info(f"Pushing to GitHub: {config.github.owner}/{repo_name} (branch: {remote_branch})")
                try:
                    mgr = GithubManager(
                        pat,
                        config.github.owner,
                        repo_name,
                        config.github.private,
                        config.github.auto_create,
                    )
                    logger.debug("Validating GitHub PAT...")
                    mgr.validate_pat()
                    if config.github.e2e_output_mode == "new_branch":
                        logger.debug(f"Ensuring branch '{repo_name}' exists...")
                        mgr.ensure_branch_exists(branch=repo_name, base_branch="main")
                    else:
                        logger.debug("Ensuring GitHub repo exists...")
                        mgr.ensure_repo_exists()
                    auth_url = mgr.get_authenticated_remote_url()
                    try:
                        engine.git_manager.set_remote("origin", auth_url)
                        engine.git_manager.push(remote="origin", branch=remote_branch)
                        logger.info(f"Pushed to {config.github.owner}/{repo_name}")
                    except GitError as push_err:
                        logger.error(f"GitHub push failed: {push_err}")
                    finally:
                        engine.git_manager.remove_remote("origin")
                except GithubError as e:
                    logger.error(f"GitHub error: {e}")

        log_file = str(config.git_repo_path / ".gdrive-backup" / "backup-log.json")
        _print_completion_summary(stats, log_path=log_file)
        sys.exit(1 if stats.failed > 0 else 0)

    except AuthError as e:
        click.echo(f"Authentication error: {e}", err=True)
        logger.error(f"Authentication error: {e}", exc_info=True)
        sys.exit(2)
    except SyncError as e:
        click.echo(f"Sync error: {e}", err=True)
        logger.error(f"Sync error: {e}", exc_info=True)
        sys.exit(2)
    except KeyboardInterrupt:
        click.echo("\nBackup interrupted by user", err=True)
        logger.info("Backup interrupted by user (KeyboardInterrupt)")
        sys.exit(130)
    except Exception as e:
        logger.exception(f"Backup failed with unexpected error: {e}")
        click.echo(f"Backup failed: {e}", err=True)
        sys.exit(2)


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
@click.pass_context
def status(ctx, config_path):
    """Show backup status."""
    resolved_config_path = _resolve_config_path(config_path)
    control_dir = _resolve_control_dir(config_path)

    try:
        config = load_config(str(resolved_config_path), str(control_dir))
    except ConfigError:
        # Try to load state directly
        state_path = control_dir / "state.json"
        state = _load_state_file(state_path)
        if not state:
            click.echo("No backup has been run yet.")
            return
        config = None

    state_path = config.state_file if config else control_dir / "state.json"
    state = _load_state_file(state_path)

    if not state:
        click.echo("No backup has been run yet.")
        return

    click.echo(f"Last run:    {state.get('last_run', 'unknown')}")
    click.echo(f"Status:      {state.get('last_run_status', 'unknown')}")
    click.echo(f"Files tracked: {len(state.get('file_cache', {}))}")
    token = state.get('start_page_token', 'none')
    click.echo(f"Change token:  {token[:20] if token else 'none'}...")


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
@click.pass_context
def config(ctx, config_path):
    """Show current configuration."""
    resolved_config_path = _resolve_config_path(config_path)

    if not resolved_config_path.exists():
        click.echo(f"No config file found at {resolved_config_path}")
        click.echo("Run 'gdrive-backup init' to create one.")
        return

    click.echo(f"Config file: {resolved_config_path}")
    click.echo("---")
    click.echo(resolved_config_path.read_text())


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
@click.pass_context
def daemon(ctx, config_path):
    """Start continuous backup mode."""
    config_path = _resolve_config_path(config_path)
    control_dir = _resolve_control_dir(config_path)

    try:
        config = load_config(str(config_path), str(control_dir))
    except ConfigError as e:
        click.echo(f"Config error: {e}", err=True)
        sys.exit(2)

    setup_logging(
        config.log_dir,
        config.log_max_size_mb,
        config.log_max_files,
        config.log_default_level,
        None,
    )

    logger.info(f"gdrive-backup daemon v{__version__} starting")

    try:
        engine = _build_engine(config)
    except AuthError as e:
        click.echo(f"Authentication error: {e}", err=True)
        sys.exit(2)

    from gdrive_backup.daemon import Daemon
    pid_file = config.control_dir / "daemon.pid"
    d = Daemon(engine, poll_interval=config.poll_interval, pid_file=pid_file)

    click.echo(f"Starting daemon (poll interval: {config.poll_interval}s)")
    click.echo("Press Ctrl+C to stop")
    try:
        d.run()
    except KeyboardInterrupt:
        click.echo("\nDaemon stopped by user")
        logger.info("Daemon stopped by user (KeyboardInterrupt)")
    except Exception as e:
        logger.exception(f"Daemon failed: {e}")
        click.echo(f"Daemon failed: {e}", err=True)
        sys.exit(2)
