# src/gdrive_backup/cli.py
"""CLI entry point for gdrive-backup."""

import glob as _glob
import json
import logging
import os
import readline
import sys
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
from gdrive_backup.sync_engine import SyncEngine, DryRunReport, DryRunSource
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


def _build_engine(config: Config) -> SyncEngine:
    """Build a SyncEngine from a validated config."""
    creds = authenticate(config.auth_method, config.credentials_file, config.token_file)
    service = build_drive_service(creds)
    drive_client = DriveClient(service)
    git_manager = GitManager.init_repo(config.git_repo_path)
    mirror_manager = MirrorManager(config.mirror_path)
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
    )


def _load_state_file(state_path: Path) -> Optional[dict]:
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
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


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
@click.pass_context
def init(ctx, config_path):
    """Set up a new backup configuration."""
    _enable_readline()
    control_dir = _resolve_control_dir(config_path)
    control_dir.mkdir(parents=True, exist_ok=True)
    (control_dir / "logs").mkdir(exist_ok=True)

    config_path = control_dir / "config.yaml"

    if config_path.exists():
        click.echo(f"Config already exists at {config_path}")
        if not click.confirm("Overwrite?"):
            return

    # Auth method
    auth_method = _prompt_text("Authentication method (oauth/service_account)", "oauth")

    # Credentials file
    creds_input = _prompt_path("Path to credentials JSON file", str(control_dir / "credentials.json"))
    creds_path = Path(creds_input).expanduser()

    if not creds_path.exists():
        click.echo(f"Note: Place your credentials file at {creds_path}")

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
        gh_owner = _prompt_text("  GitHub owner (user or org)")
        gh_repo = _prompt_text("  Repository name")
        gh_private = click.confirm("  Private repo?", default=True)
        gh_auto_create = click.confirm("  Auto-create if missing?", default=True)
        gh_pat = _prompt_text("  GitHub PAT (leave blank to use GITHUB_PAT env var)")

        if gh_pat:
            try:
                mgr = GithubManager(gh_pat, gh_owner, gh_repo, gh_private, gh_auto_create)
                mgr.validate_pat()
                click.echo("  PAT validated successfully.")
            except GithubError as e:
                click.echo(f"  Warning: PAT validation failed: {e}")
                if not click.confirm("  Save anyway?", default=False):
                    gh_pat = ""

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

    with open(config_path, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False)
    os.chmod(config_path, 0o600)

    # Initialize git repo
    git_path = Path(git_repo_path).expanduser()
    GitManager.init_repo(git_path)

    # Create mirror directory
    Path(mirror_path).expanduser().mkdir(parents=True, exist_ok=True)

    click.echo(f"\nSetup complete!")
    click.echo(f"  Config: {config_path}")
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

    try:
        engine = _build_engine(config)
        if dry_run:
            github_repo = (
                f"{config.github.owner}/{config.github.repo}"
                if config.github and config.github.enabled
                else None
            )
            report = engine.run_dry(
                git_repo_path=str(config.git_repo_path),
                mirror_path=str(config.mirror_path),
                auth_method=config.auth_method,
                max_file_size_mb=config.max_file_size_mb,
                github_repo=github_repo,
            )
            _print_dry_run_report(report)
            return
        stats = engine.run()

        # GitHub push (skipped when --dry-run; dry_run branch already returned above)
        if config.github and config.github.enabled:
            pat = _resolve_pat(config)
            if not pat:
                click.echo("GitHub push skipped: no PAT found (set GITHUB_PAT or github.pat in config)", err=True)
            else:
                repo_name = _resolve_repo_name(config)
                remote_branch = repo_name if config.github.e2e_output_mode == "new_branch" else "main"
                try:
                    mgr = GithubManager(
                        pat,
                        config.github.owner,
                        repo_name,
                        config.github.private,
                        config.github.auto_create,
                    )
                    mgr.validate_pat()
                    if config.github.e2e_output_mode == "new_branch":
                        mgr.ensure_branch_exists(branch=repo_name, base_branch="main")
                    else:
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

        click.echo(f"Backup complete: {stats.summary()}")
        sys.exit(1 if stats.failed > 0 else 0)
    except AuthError as e:
        click.echo(f"Authentication error: {e}", err=True)
        sys.exit(2)
    except Exception as e:
        logger.exception(f"Backup failed: {e}")
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
    click.echo(f"Change token:  {state.get('start_page_token', 'none')[:20]}...")


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
    except Exception as e:
        logger.exception(f"Daemon failed: {e}")
        click.echo(f"Daemon failed: {e}", err=True)
        sys.exit(2)
