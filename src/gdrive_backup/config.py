# src/gdrive_backup/config.py
"""Configuration loading, validation, and path resolution."""

import logging
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import yaml

logger = logging.getLogger(__name__)

DEFAULT_CONTROL_DIR = Path.home() / ".gdrive-backup"
VALID_AUTH_METHODS = ("oauth", "service_account")
VALID_LOG_LEVELS = ("debug", "info", "warning", "error")


class ConfigError(Exception):
    """Raised when configuration is invalid."""


@dataclass
class Config:
    """Validated, resolved configuration."""

    # Auth
    auth_method: str
    credentials_file: Path
    token_file: Path

    # Backup paths
    git_repo_path: Path
    mirror_path: Path

    # Scope
    include_shared: bool
    folder_ids: List[str]

    # Sync
    state_file: Path

    # Limits
    max_file_size_mb: int

    # Logging
    log_max_size_mb: int
    log_max_files: int
    log_default_level: str
    log_dir: Path

    # Daemon
    poll_interval: int

    # Control dir
    control_dir: Path


def load_config(config_path: str, control_dir: Optional[str] = None) -> Config:
    """Load and validate config from a YAML file.

    Args:
        config_path: Path to the config YAML file.
        control_dir: Path to the control directory. Defaults to ~/.gdrive-backup/.

    Returns:
        Validated Config object with resolved paths.

    Raises:
        ConfigError: If the config file is missing, unparseable, or invalid.
    """
    config_path = Path(config_path)
    ctrl_dir = Path(control_dir) if control_dir else DEFAULT_CONTROL_DIR

    if not config_path.exists():
        raise ConfigError(f"Config file not found: {config_path}")

    _check_permissions(config_path)

    try:
        with open(config_path) as f:
            raw = yaml.safe_load(f)
    except yaml.YAMLError as e:
        raise ConfigError(f"Failed to parse config: {e}")

    if not isinstance(raw, dict):
        raise ConfigError("Config file must contain a YAML mapping")

    return _validate_and_resolve(raw, ctrl_dir)


def _check_permissions(path: Path) -> None:
    """Warn if config file has overly open permissions."""
    try:
        mode = path.stat().st_mode
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            logger.warning(
                f"Config file {path} has open permissions ({oct(mode)}). "
                f"Consider restricting to owner-only (chmod 600)."
            )
    except OSError:
        pass


def _validate_and_resolve(raw: dict, control_dir: Path) -> Config:
    """Validate raw config dict and resolve paths."""
    auth = raw.get("auth") or {}
    backup = raw.get("backup") or {}
    scope = raw.get("scope") or {}
    sync = raw.get("sync") or {}
    logging_cfg = raw.get("logging") or {}
    daemon = raw.get("daemon") or {}

    # Auth method
    auth_method = auth.get("method", "oauth")
    if auth_method not in VALID_AUTH_METHODS:
        raise ConfigError(
            f"Invalid auth.method: '{auth_method}'. Must be one of {VALID_AUTH_METHODS}"
        )

    # Auth paths (relative to control dir)
    credentials_file = control_dir / auth.get("credentials_file", "credentials.json")
    token_file = control_dir / auth.get("token_file", "token.json")

    # Backup paths (absolute or ~ expansion)
    git_repo_path = Path(backup.get("git_repo_path", "~/gdrive-backup-repo")).expanduser()
    mirror_path = Path(backup.get("mirror_path", "~/gdrive-backup-mirror")).expanduser()

    # Scope
    include_shared = scope.get("include_shared", False)
    folder_ids = scope.get("folder_ids", [])

    # Sync state (relative to control dir)
    state_file = control_dir / sync.get("state_file", "state.json")

    # File size limit
    max_file_size_mb = raw.get("max_file_size_mb", 0)
    if not isinstance(max_file_size_mb, (int, float)) or max_file_size_mb < 0:
        raise ConfigError("max_file_size_mb must be a non-negative number")

    # Logging
    log_max_size_mb = logging_cfg.get("max_size_mb", 10)
    log_max_files = logging_cfg.get("max_files", 5)
    if not isinstance(log_max_size_mb, (int, float)) or log_max_size_mb <= 0:
        raise ConfigError("logging.max_size_mb must be a positive number")
    if not isinstance(log_max_files, (int, float)) or log_max_files <= 0:
        raise ConfigError("logging.max_files must be a positive number")
    log_default_level = logging_cfg.get("default_level", "info")
    if log_default_level not in VALID_LOG_LEVELS:
        raise ConfigError(
            f"Invalid logging.default_level: '{log_default_level}'. "
            f"Must be one of {VALID_LOG_LEVELS}"
        )
    log_dir = control_dir / "logs"

    # Daemon
    poll_interval = daemon.get("poll_interval", 300)
    if not isinstance(poll_interval, (int, float)) or poll_interval <= 0:
        raise ConfigError("daemon.poll_interval must be a positive number")

    return Config(
        auth_method=auth_method,
        credentials_file=credentials_file,
        token_file=token_file,
        git_repo_path=git_repo_path,
        mirror_path=mirror_path,
        include_shared=include_shared,
        folder_ids=folder_ids,
        state_file=state_file,
        max_file_size_mb=int(max_file_size_mb),
        log_max_size_mb=log_max_size_mb,
        log_max_files=log_max_files,
        log_default_level=log_default_level,
        log_dir=log_dir,
        poll_interval=int(poll_interval),
        control_dir=control_dir,
    )
