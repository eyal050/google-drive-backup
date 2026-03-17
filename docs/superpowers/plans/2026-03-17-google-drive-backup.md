# Google Drive Backup Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Python CLI tool that backs up a Google Drive account — text files to a git repo, binary files to a mirror directory.

**Architecture:** Core library with focused modules (auth, drive_client, classifier, git_manager, mirror_manager, sync_engine) + thin CLI shell. Each module has one clear responsibility and communicates through well-defined interfaces.

**Tech Stack:** Python 3.11+, click, google-api-python-client, google-auth, google-auth-oauthlib, gitpython, python-magic, pyyaml, pytest

**Spec:** `docs/superpowers/specs/2026-03-17-google-drive-backup-design.md`

---

## File Map

| File | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata, dependencies, entry point |
| `config.example.yaml` | Example config for users |
| `src/gdrive_backup/__init__.py` | Package init, version |
| `src/gdrive_backup/config.py` | Load, validate, resolve config paths |
| `src/gdrive_backup/logging_setup.py` | Configure rotating file + console logging |
| `src/gdrive_backup/auth.py` | OAuth 2.0 and service account authentication |
| `src/gdrive_backup/drive_client.py` | Google Drive API wrapper with rate limiting |
| `src/gdrive_backup/classifier.py` | MIME + content-based text/binary classification |
| `src/gdrive_backup/git_manager.py` | Git repo add/remove/commit operations |
| `src/gdrive_backup/mirror_manager.py` | Binary file write/delete in mirror dir |
| `src/gdrive_backup/sync_engine.py` | Orchestrates full backup flow |
| `src/gdrive_backup/cli.py` | Click CLI entry point |
| `src/gdrive_backup/daemon.py` | Polling daemon mode |
| `tests/conftest.py` | Shared fixtures |
| `tests/test_config.py` | Config loading/validation tests |
| `tests/test_classifier.py` | Classification logic tests |
| `tests/test_git_manager.py` | Git operations tests |
| `tests/test_mirror_manager.py` | Mirror operations tests |
| `tests/test_auth.py` | Auth flow tests |
| `tests/test_drive_client.py` | Drive client tests (mocked API) |
| `tests/test_sync_engine.py` | Sync orchestration tests |
| `tests/test_cli.py` | CLI command tests |
| `tests/test_daemon.py` | Daemon mode tests |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `src/gdrive_backup/__init__.py`
- Create: `config.example.yaml`
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `pyproject.toml`**

```toml
[build-system]
requires = ["setuptools>=68.0", "setuptools-scm"]
build-backend = "setuptools.build_meta"

[project]
name = "gdrive-backup"
version = "0.1.0"
description = "Back up Google Drive to a git repo (text files) and mirror directory (binary files)"
readme = "README.md"
requires-python = ">=3.11"
license = {text = "MIT"}
dependencies = [
    "click>=8.1",
    "google-api-python-client>=2.100",
    "google-auth>=2.23",
    "google-auth-oauthlib>=1.1",
    "gitpython>=3.1",
    "python-magic>=0.4",
    "pyyaml>=6.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-cov>=4.1",
]

[project.scripts]
gdrive-backup = "gdrive_backup.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Create `src/gdrive_backup/__init__.py`**

```python
"""Google Drive Backup — back up your Drive to git + mirror."""

__version__ = "0.1.0"
```

- [ ] **Step 3: Create `config.example.yaml`**

```yaml
# Google Drive Backup Configuration
# Copy to ~/.gdrive-backup/config.yaml and edit

# Authentication
auth:
  method: oauth  # "oauth" or "service_account"
  credentials_file: credentials.json  # Relative to ~/.gdrive-backup/
  token_file: token.json  # Relative to ~/.gdrive-backup/

# Backup targets
backup:
  git_repo_path: ~/gdrive-backup-repo
  mirror_path: ~/gdrive-backup-mirror

# What to back up
scope:
  include_shared: false
  folder_ids: []  # Empty = entire Drive

# Sync settings
sync:
  state_file: state.json  # Relative to ~/.gdrive-backup/

# File size limit in MB (0 = no limit)
max_file_size_mb: 0

# Logging
logging:
  max_size_mb: 10
  max_files: 5
  default_level: info  # debug, info, warning, error

# Daemon mode
daemon:
  poll_interval: 300  # Seconds between checks
```

- [ ] **Step 4: Create `tests/conftest.py`**

```python
"""Shared test fixtures."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def tmp_dir(tmp_path):
    """Provide a temporary directory."""
    return tmp_path


@pytest.fixture
def control_dir(tmp_path):
    """Create a temporary control directory (~/.gdrive-backup/ equivalent)."""
    d = tmp_path / "control"
    d.mkdir()
    (d / "logs").mkdir()
    return d


@pytest.fixture
def git_repo_dir(tmp_path):
    """Create a temporary directory for the git repo."""
    d = tmp_path / "git-repo"
    d.mkdir()
    return d


@pytest.fixture
def mirror_dir(tmp_path):
    """Create a temporary directory for the mirror."""
    d = tmp_path / "mirror"
    d.mkdir()
    return d


@pytest.fixture
def sample_config(control_dir, git_repo_dir, mirror_dir):
    """Create a valid sample config dict."""
    return {
        "auth": {
            "method": "oauth",
            "credentials_file": "credentials.json",
            "token_file": "token.json",
        },
        "backup": {
            "git_repo_path": str(git_repo_dir),
            "mirror_path": str(mirror_dir),
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


@pytest.fixture
def config_file(control_dir, sample_config):
    """Write sample config to a file and return path."""
    config_path = control_dir / "config.yaml"
    with open(config_path, "w") as f:
        yaml.dump(sample_config, f)
    return config_path
```

- [ ] **Step 5: Install project in dev mode and verify**

Run: `cd /home/eyal/repos/google-drive-backup && python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`
Expected: Installs successfully, `gdrive-backup` entry point registered.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/ tests/conftest.py config.example.yaml
git commit -m "feat: project scaffolding with dependencies and test fixtures"
```

---

## Task 2: Configuration Module

**Files:**
- Create: `src/gdrive_backup/config.py`
- Create: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for config loading**

```python
# tests/test_config.py
"""Tests for configuration loading and validation."""

import os
import stat
from pathlib import Path

import pytest
import yaml

from gdrive_backup.config import (
    Config,
    ConfigError,
    load_config,
    DEFAULT_CONTROL_DIR,
)


class TestLoadConfig:
    def test_load_valid_config(self, config_file, sample_config, control_dir):
        config = load_config(str(config_file), str(control_dir))
        assert config.auth_method == "oauth"
        assert config.include_shared is False

    def test_load_missing_file_raises(self, tmp_path, control_dir):
        with pytest.raises(ConfigError, match="not found"):
            load_config(str(tmp_path / "missing.yaml"), str(control_dir))

    def test_load_invalid_yaml_raises(self, control_dir):
        bad = control_dir / "bad.yaml"
        bad.write_text(": : invalid: [")
        with pytest.raises(ConfigError, match="parse"):
            load_config(str(bad), str(control_dir))


class TestPathResolution:
    def test_auth_paths_resolve_relative_to_control_dir(self, config_file, control_dir):
        config = load_config(str(config_file), str(control_dir))
        assert config.credentials_file == control_dir / "credentials.json"
        assert config.token_file == control_dir / "token.json"
        assert config.state_file == control_dir / "state.json"

    def test_backup_paths_expand_tilde(self, control_dir, sample_config):
        sample_config["backup"]["git_repo_path"] = "~/my-backup-repo"
        sample_config["backup"]["mirror_path"] = "~/my-mirror"
        config_path = control_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sample_config, f)
        config = load_config(str(config_path), str(control_dir))
        assert str(config.git_repo_path).startswith(str(Path.home()))


class TestValidation:
    def test_invalid_auth_method_raises(self, control_dir, sample_config):
        sample_config["auth"]["method"] = "invalid"
        config_path = control_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sample_config, f)
        with pytest.raises(ConfigError, match="auth.method"):
            load_config(str(config_path), str(control_dir))

    def test_negative_max_file_size_raises(self, control_dir, sample_config):
        sample_config["max_file_size_mb"] = -1
        config_path = control_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sample_config, f)
        with pytest.raises(ConfigError, match="max_file_size_mb"):
            load_config(str(config_path), str(control_dir))

    def test_invalid_log_level_raises(self, control_dir, sample_config):
        sample_config["logging"]["default_level"] = "trace"
        config_path = control_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sample_config, f)
        with pytest.raises(ConfigError, match="log"):
            load_config(str(config_path), str(control_dir))

    def test_negative_poll_interval_raises(self, control_dir, sample_config):
        sample_config["daemon"]["poll_interval"] = -10
        config_path = control_dir / "config.yaml"
        with open(config_path, "w") as f:
            yaml.dump(sample_config, f)
        with pytest.raises(ConfigError, match="poll_interval"):
            load_config(str(config_path), str(control_dir))


class TestConfigPermissions:
    def test_warns_on_open_permissions(self, config_file, control_dir, caplog):
        os.chmod(config_file, stat.S_IRWXU | stat.S_IRWXG | stat.S_IRWXO)
        import logging
        with caplog.at_level(logging.WARNING):
            load_config(str(config_file), str(control_dir))
        assert any("permission" in r.message.lower() for r in caplog.records)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eyal/repos/google-drive-backup && source .venv/bin/activate && python -m pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gdrive_backup.config'`

- [ ] **Step 3: Implement `config.py`**

```python
# src/gdrive_backup/config.py
"""Configuration loading, validation, and path resolution."""

import logging
import os
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
    auth = raw.get("auth", {})
    backup = raw.get("backup", {})
    scope = raw.get("scope", {})
    sync = raw.get("sync", {})
    logging_cfg = raw.get("logging", {})
    daemon = raw.get("daemon", {})

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/config.py tests/test_config.py
git commit -m "feat: configuration loading with validation and path resolution"
```

---

## Task 3: Logging Setup

**Files:**
- Create: `src/gdrive_backup/logging_setup.py`

- [ ] **Step 1: Implement logging setup**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add src/gdrive_backup/logging_setup.py
git commit -m "feat: rotating file + console logging setup"
```

---

## Task 4: Authentication Module

**Files:**
- Create: `src/gdrive_backup/auth.py`
- Create: `tests/test_auth.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_auth.py
"""Tests for authentication module."""

import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gdrive_backup.auth import (
    AuthError,
    authenticate,
    _validate_credentials_file,
    _set_secure_permissions,
)


class TestValidateCredentialsFile:
    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(AuthError, match="not found"):
            _validate_credentials_file(tmp_path / "missing.json")

    def test_valid_file_passes(self, tmp_path):
        creds = tmp_path / "credentials.json"
        creds.write_text('{"installed": {}}')
        os.chmod(creds, 0o600)
        _validate_credentials_file(creds)  # Should not raise

    def test_open_permissions_raises(self, tmp_path):
        creds = tmp_path / "credentials.json"
        creds.write_text('{"installed": {}}')
        os.chmod(creds, 0o644)
        with pytest.raises(AuthError, match="permission"):
            _validate_credentials_file(creds)


class TestSetSecurePermissions:
    def test_sets_600(self, tmp_path):
        f = tmp_path / "token.json"
        f.write_text("{}")
        _set_secure_permissions(f)
        mode = f.stat().st_mode & 0o777
        assert mode == 0o600


class TestAuthenticate:
    @patch("gdrive_backup.auth._oauth_flow")
    def test_oauth_method(self, mock_flow, tmp_path):
        creds_file = tmp_path / "credentials.json"
        creds_file.write_text('{"installed": {}}')
        os.chmod(creds_file, 0o600)
        token_file = tmp_path / "token.json"

        mock_creds = MagicMock()
        mock_creds.valid = True
        mock_flow.return_value = mock_creds

        result = authenticate("oauth", creds_file, token_file)
        assert result is not None

    @patch("gdrive_backup.auth._service_account_flow")
    def test_service_account_method(self, mock_flow, tmp_path):
        creds_file = tmp_path / "sa-key.json"
        creds_file.write_text('{"type": "service_account"}')
        os.chmod(creds_file, 0o600)
        token_file = tmp_path / "token.json"

        mock_creds = MagicMock()
        mock_flow.return_value = mock_creds

        result = authenticate("service_account", creds_file, token_file)
        assert result is not None

    def test_invalid_method_raises(self, tmp_path):
        with pytest.raises(AuthError, match="method"):
            authenticate("invalid", tmp_path / "c.json", tmp_path / "t.json")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'gdrive_backup.auth'`

- [ ] **Step 3: Implement `auth.py`**

```python
# src/gdrive_backup/auth.py
"""OAuth 2.0 and service account authentication for Google Drive API."""

import json
import logging
import os
import stat
from pathlib import Path
from typing import Optional

from google.auth.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


class AuthError(Exception):
    """Raised when authentication fails."""


def authenticate(
    method: str,
    credentials_file: Path,
    token_file: Path,
) -> Credentials:
    """Authenticate with Google Drive API.

    Args:
        method: "oauth" or "service_account".
        credentials_file: Path to credentials JSON file.
        token_file: Path to store/load OAuth tokens.

    Returns:
        Authenticated credentials object.

    Raises:
        AuthError: If authentication fails.
    """
    if method == "oauth":
        _validate_credentials_file(credentials_file)
        return _oauth_flow(credentials_file, token_file)
    elif method == "service_account":
        _validate_credentials_file(credentials_file)
        return _service_account_flow(credentials_file)
    else:
        raise AuthError(f"Invalid auth method: '{method}'. Must be 'oauth' or 'service_account'")


def build_drive_service(credentials: Credentials):
    """Build an authenticated Google Drive API service.

    Args:
        credentials: Authenticated credentials.

    Returns:
        Google Drive API service object.
    """
    return build("drive", "v3", credentials=credentials)


def _oauth_flow(credentials_file: Path, token_file: Path) -> Credentials:
    """Run OAuth 2.0 flow with token caching."""
    creds = None

    if token_file.exists():
        try:
            creds = OAuthCredentials.from_authorized_user_file(str(token_file), SCOPES)
        except Exception as e:
            logger.warning(f"Failed to load cached token: {e}")

    if creds and creds.valid:
        logger.debug("Using cached OAuth token")
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            logger.info("Refreshing expired OAuth token")
            creds.refresh(Request())
            _save_token(creds, token_file)
            return creds
        except Exception as e:
            logger.warning(f"Token refresh failed: {e}")

    logger.info("Starting OAuth consent flow (browser will open)")
    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
        creds = flow.run_local_server(port=0)
    except Exception as e:
        raise AuthError(f"OAuth flow failed: {e}")

    _save_token(creds, token_file)
    return creds


def _service_account_flow(credentials_file: Path) -> Credentials:
    """Authenticate using a service account key file."""
    try:
        creds = service_account.Credentials.from_service_account_file(
            str(credentials_file), scopes=SCOPES
        )
        logger.info("Authenticated with service account")
        return creds
    except Exception as e:
        raise AuthError(f"Service account auth failed: {e}")


def _save_token(creds: Credentials, token_file: Path) -> None:
    """Save OAuth token to file with secure permissions."""
    token_file.parent.mkdir(parents=True, exist_ok=True)
    with open(token_file, "w") as f:
        f.write(creds.to_json())
    _set_secure_permissions(token_file)
    logger.debug(f"Token saved to {token_file}")


def _validate_credentials_file(path: Path) -> None:
    """Validate that a credentials file exists and has secure permissions."""
    if not path.exists():
        raise AuthError(f"Credentials file not found: {path}")

    mode = path.stat().st_mode
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise AuthError(
            f"Credentials file {path} has insecure permissions ({oct(mode & 0o777)}). "
            f"Run: chmod 600 {path}"
        )


def _set_secure_permissions(path: Path) -> None:
    """Set file permissions to owner-only (600)."""
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_auth.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/auth.py tests/test_auth.py
git commit -m "feat: OAuth 2.0 and service account authentication"
```

---

## Task 5: Drive Client Module

**Files:**
- Create: `src/gdrive_backup/drive_client.py`
- Create: `tests/test_drive_client.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_drive_client.py
"""Tests for Google Drive API client wrapper."""

import time
from unittest.mock import MagicMock, patch, call

import pytest

from gdrive_backup.drive_client import (
    DriveClient,
    DriveFile,
    DriveChange,
    RateLimiter,
)


class TestRateLimiter:
    def test_allows_requests_under_limit(self):
        limiter = RateLimiter(max_per_second=100)
        # Should not block for a single request
        start = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    def test_reduce_rate(self):
        limiter = RateLimiter(max_per_second=100)
        limiter.reduce_rate()
        assert limiter.max_per_second == 50


class TestDriveClient:
    @pytest.fixture
    def mock_service(self):
        return MagicMock()

    @pytest.fixture
    def client(self, mock_service):
        return DriveClient(mock_service)

    def test_list_all_files_paginates(self, client, mock_service):
        # First page returns files + nextPageToken
        page1 = {"files": [{"id": "1", "name": "a.txt", "mimeType": "text/plain",
                            "parents": ["root"], "md5Checksum": "abc", "size": "100",
                            "modifiedTime": "2026-01-01T00:00:00Z"}],
                 "nextPageToken": "token2"}
        page2 = {"files": [{"id": "2", "name": "b.txt", "mimeType": "text/plain",
                            "parents": ["root"], "md5Checksum": "def", "size": "200",
                            "modifiedTime": "2026-01-02T00:00:00Z"}]}

        mock_list = mock_service.files.return_value.list
        mock_list.return_value.execute.side_effect = [page1, page2]

        files = list(client.list_all_files())
        assert len(files) == 2
        assert files[0].id == "1"
        assert files[1].id == "2"

    def test_get_start_page_token(self, client, mock_service):
        mock_service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
            "startPageToken": "12345"
        }
        token = client.get_start_page_token()
        assert token == "12345"

    def test_get_changes(self, client, mock_service):
        response = {
            "changes": [
                {"fileId": "1", "removed": False, "file": {
                    "id": "1", "name": "a.txt", "mimeType": "text/plain",
                    "parents": ["root"], "md5Checksum": "abc", "size": "100",
                    "modifiedTime": "2026-01-01T00:00:00Z", "trashed": False
                }}
            ],
            "newStartPageToken": "99999",
        }
        mock_service.changes.return_value.list.return_value.execute.return_value = response

        changes, new_token = client.get_changes("12345")
        assert len(changes) == 1
        assert changes[0].file_id == "1"
        assert changes[0].removed is False
        assert new_token == "99999"

    def test_download_file(self, client, mock_service):
        mock_request = MagicMock()
        mock_service.files.return_value.get_media.return_value = mock_request

        with patch("gdrive_backup.drive_client.MediaIoBaseDownload") as mock_dl:
            mock_dl_instance = MagicMock()
            mock_dl.return_value = mock_dl_instance
            mock_dl_instance.next_chunk.side_effect = [
                (MagicMock(progress=MagicMock(return_value=0.5)), False),
                (MagicMock(progress=MagicMock(return_value=1.0)), True),
            ]
            content = client.download_file("file_id_1")
            assert content is not None

    def test_export_file(self, client, mock_service):
        mock_request = MagicMock()
        mock_service.files.return_value.export_media.return_value = mock_request

        with patch("gdrive_backup.drive_client.MediaIoBaseDownload") as mock_dl:
            mock_dl_instance = MagicMock()
            mock_dl.return_value = mock_dl_instance
            mock_dl_instance.next_chunk.return_value = (
                MagicMock(progress=MagicMock(return_value=1.0)), True
            )
            content = client.export_file("file_id_1", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            assert content is not None

    def test_resolve_file_path(self, client, mock_service):
        # Mock folder hierarchy: root -> folder1 -> file
        mock_get = mock_service.files.return_value.get
        mock_get.return_value.execute.side_effect = [
            {"name": "folder1", "parents": ["root_id"]},
            {"name": "My Drive", "parents": []},
        ]
        path = client.resolve_file_path(["folder1_id"])
        assert "folder1" in path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_drive_client.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `drive_client.py`**

```python
# src/gdrive_backup/drive_client.py
"""Google Drive API wrapper with rate limiting and pagination."""

import io
import logging
import time
from dataclasses import dataclass
from typing import Generator, List, Optional, Tuple

from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Google native MIME types that need export
GOOGLE_EXPORT_MAP = {
    "application/vnd.google-apps.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

GOOGLE_EXPORT_EXTENSIONS = {
    "application/vnd.google-apps.document": ".docx",
    "application/vnd.google-apps.spreadsheet": ".xlsx",
    "application/vnd.google-apps.presentation": ".pptx",
}

# Google native types that can't be downloaded (no export available)
GOOGLE_SKIP_TYPES = {
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.map",
    "application/vnd.google-apps.site",
    "application/vnd.google-apps.shortcut",
    "application/vnd.google-apps.folder",
}


@dataclass
class DriveFile:
    """Represents a file from Google Drive."""
    id: str
    name: str
    mime_type: str
    parents: List[str]
    md5: Optional[str]
    size: Optional[int]
    modified_time: str

    @property
    def is_google_native(self) -> bool:
        return self.mime_type.startswith("application/vnd.google-apps.")

    @property
    def is_exportable(self) -> bool:
        return self.mime_type in GOOGLE_EXPORT_MAP

    @property
    def should_skip(self) -> bool:
        return self.mime_type in GOOGLE_SKIP_TYPES

    @property
    def export_mime_type(self) -> Optional[str]:
        return GOOGLE_EXPORT_MAP.get(self.mime_type)

    @property
    def export_extension(self) -> Optional[str]:
        return GOOGLE_EXPORT_EXTENSIONS.get(self.mime_type)


@dataclass
class DriveChange:
    """Represents a change from the Drive changes API."""
    file_id: str
    removed: bool
    file: Optional[DriveFile]


class RateLimiter:
    """Simple rate limiter using token bucket algorithm."""

    def __init__(self, max_per_second: int = 100):
        self.max_per_second = max_per_second
        self._min_interval = 1.0 / max_per_second
        self._last_request = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def reduce_rate(self) -> None:
        self.max_per_second = max(1, self.max_per_second // 2)
        self._min_interval = 1.0 / self.max_per_second
        logger.warning(f"Rate reduced to {self.max_per_second} requests/second")


class DriveClient:
    """Wrapper around Google Drive API with rate limiting."""

    FILE_FIELDS = "id, name, mimeType, parents, md5Checksum, size, modifiedTime"

    def __init__(self, service, max_retries: int = 3):
        self._service = service
        self._limiter = RateLimiter()
        self._max_retries = max_retries
        self._path_cache: dict[str, str] = {}

    def list_all_files(
        self,
        include_shared: bool = False,
        folder_ids: Optional[List[str]] = None,
    ) -> Generator[DriveFile, None, None]:
        """List all files in Drive, handling pagination.

        Args:
            include_shared: Include files shared with the user.
            folder_ids: Limit to specific folder IDs. Empty = all.

        Yields:
            DriveFile objects.
        """
        query_parts = ["trashed = false"]
        if not include_shared:
            query_parts.append("'me' in owners")
        if folder_ids:
            folder_q = " or ".join(f"'{fid}' in parents" for fid in folder_ids)
            query_parts.append(f"({folder_q})")

        query = " and ".join(query_parts)
        page_token = None
        file_count = 0

        while True:
            self._limiter.wait()
            response = self._execute_with_retry(
                self._service.files().list(
                    q=query,
                    fields=f"nextPageToken, files({self.FILE_FIELDS})",
                    pageSize=1000,
                    pageToken=page_token,
                )
            )

            for f in response.get("files", []):
                file_count += 1
                if file_count % 100 == 0:
                    logger.info(f"Listed {file_count} files...")
                yield self._parse_file(f)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"Listed {file_count} files total")

    def get_start_page_token(self) -> str:
        """Get the current start page token for changes API."""
        self._limiter.wait()
        response = self._execute_with_retry(
            self._service.changes().getStartPageToken()
        )
        return response["startPageToken"]

    def get_changes(
        self, start_page_token: str
    ) -> Tuple[List[DriveChange], Optional[str]]:
        """Get changes since the given page token.

        Returns:
            Tuple of (list of changes, new start page token or None if more pages).
        """
        all_changes: List[DriveChange] = []
        page_token = start_page_token
        new_start_token = None

        while page_token:
            self._limiter.wait()
            response = self._execute_with_retry(
                self._service.changes().list(
                    pageToken=page_token,
                    fields=f"nextPageToken, newStartPageToken, changes(fileId, removed, file({self.FILE_FIELDS}, trashed))",
                    pageSize=1000,
                )
            )

            for change in response.get("changes", []):
                file_data = change.get("file")
                removed = change.get("removed", False)
                trashed = file_data.get("trashed", False) if file_data else False

                drive_file = self._parse_file(file_data) if file_data and not trashed else None

                all_changes.append(DriveChange(
                    file_id=change["fileId"],
                    removed=removed or trashed,
                    file=drive_file,
                ))

            page_token = response.get("nextPageToken")
            new_start_token = response.get("newStartPageToken")

        return all_changes, new_start_token

    def download_file(self, file_id: str) -> bytes:
        """Download a regular (non-Google-native) file.

        Returns:
            File content as bytes.
        """
        self._limiter.wait()
        request = self._service.files().get_media(fileId=file_id)
        return self._download_media(request)

    def export_file(self, file_id: str, mime_type: str) -> bytes:
        """Export a Google native file to the specified MIME type.

        Returns:
            Exported file content as bytes.
        """
        self._limiter.wait()
        request = self._service.files().export_media(fileId=file_id, mimeType=mime_type)
        return self._download_media(request)

    def resolve_file_path(self, parent_ids: List[str]) -> str:
        """Resolve parent IDs to a folder path string.

        Uses caching to avoid redundant API calls.
        """
        if not parent_ids:
            return ""

        parent_id = parent_ids[0]  # Files typically have one parent
        if parent_id in self._path_cache:
            return self._path_cache[parent_id]

        parts = []
        current_id = parent_id
        while current_id:
            if current_id in self._path_cache:
                parts.append(self._path_cache[current_id])
                break

            self._limiter.wait()
            try:
                folder = self._execute_with_retry(
                    self._service.files().get(
                        fileId=current_id, fields="name, parents"
                    )
                )
            except Exception:
                break

            parents = folder.get("parents", [])
            if not parents:
                break  # Reached root

            parts.append(folder["name"])
            current_id = parents[0]

        parts.reverse()
        path = "/".join(parts)
        self._path_cache[parent_id] = path
        return path

    def _download_media(self, request) -> bytes:
        """Download media content from a request object."""
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        return buffer.getvalue()

    def _execute_with_retry(self, request):
        """Execute an API request with retry logic."""
        for attempt in range(self._max_retries):
            try:
                return request.execute()
            except HttpError as e:
                if e.resp.status == 429:
                    retry_after = int(e.resp.get("Retry-After", 2 ** attempt))
                    logger.warning(f"Rate limited. Retrying in {retry_after}s...")
                    self._limiter.reduce_rate()
                    time.sleep(retry_after)
                elif e.resp.status >= 500:
                    wait = 2 ** attempt
                    logger.warning(f"Server error {e.resp.status}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise
            except Exception as e:
                if attempt < self._max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"Request failed: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError(f"Request failed after {self._max_retries} retries")

    def _parse_file(self, data: dict) -> DriveFile:
        """Parse API response dict into DriveFile."""
        size_str = data.get("size")
        return DriveFile(
            id=data["id"],
            name=data["name"],
            mime_type=data["mimeType"],
            parents=data.get("parents", []),
            md5=data.get("md5Checksum"),
            size=int(size_str) if size_str else None,
            modified_time=data.get("modifiedTime", ""),
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_drive_client.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/drive_client.py tests/test_drive_client.py
git commit -m "feat: Drive API client with rate limiting and pagination"
```

---

## Task 6: File Classifier

**Files:**
- Create: `src/gdrive_backup/classifier.py`
- Create: `tests/test_classifier.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_classifier.py
"""Tests for file type classification."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gdrive_backup.classifier import (
    FileClassifier,
    FileType,
    sanitize_filename,
)


class TestSanitizeFilename:
    def test_normal_name_unchanged(self):
        assert sanitize_filename("report.txt") == "report.txt"

    def test_strips_path_traversal(self):
        assert ".." not in sanitize_filename("../../etc/passwd")

    def test_strips_absolute_path(self):
        result = sanitize_filename("/etc/passwd")
        assert not result.startswith("/")

    def test_replaces_null_bytes(self):
        assert "\x00" not in sanitize_filename("file\x00name.txt")

    def test_empty_name_gets_default(self):
        result = sanitize_filename("")
        assert len(result) > 0


class TestFileClassifier:
    @pytest.fixture
    def classifier(self):
        return FileClassifier()

    def test_text_mime_classified_as_text(self, classifier):
        assert classifier.classify_by_mime("text/plain") == FileType.TEXT
        assert classifier.classify_by_mime("text/html") == FileType.TEXT
        assert classifier.classify_by_mime("application/json") == FileType.TEXT
        assert classifier.classify_by_mime("application/xml") == FileType.TEXT
        assert classifier.classify_by_mime("application/javascript") == FileType.TEXT
        assert classifier.classify_by_mime("application/x-yaml") == FileType.TEXT
        assert classifier.classify_by_mime("application/x-sh") == FileType.TEXT
        assert classifier.classify_by_mime("application/sql") == FileType.TEXT

    def test_binary_mime_classified_as_binary(self, classifier):
        assert classifier.classify_by_mime("image/png") == FileType.BINARY
        assert classifier.classify_by_mime("image/jpeg") == FileType.BINARY
        assert classifier.classify_by_mime("application/pdf") == FileType.BINARY
        assert classifier.classify_by_mime("video/mp4") == FileType.BINARY
        assert classifier.classify_by_mime("audio/mpeg") == FileType.BINARY
        assert classifier.classify_by_mime("application/zip") == FileType.BINARY
        assert classifier.classify_by_mime("application/octet-stream") == FileType.BINARY

    def test_office_formats_classified_as_binary(self, classifier):
        assert classifier.classify_by_mime(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ) == FileType.BINARY

    def test_google_native_classified_as_binary(self, classifier):
        # Google native types are exported to Office formats = binary
        assert classifier.classify_by_mime(
            "application/vnd.google-apps.document"
        ) == FileType.BINARY

    def test_unknown_mime_returns_unknown(self, classifier):
        assert classifier.classify_by_mime("application/x-unknown-thing") == FileType.UNKNOWN

    def test_classify_by_content_text(self, classifier):
        content = b"Hello, this is plain text content.\nWith newlines.\n"
        assert classifier.classify_by_content(content) == FileType.TEXT

    def test_classify_by_content_binary(self, classifier):
        content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        assert classifier.classify_by_content(content) == FileType.BINARY

    def test_classify_combined_uses_mime_first(self, classifier):
        result = classifier.classify("text/plain", b"\x89PNG binary content")
        assert result == FileType.TEXT  # MIME takes priority

    def test_classify_combined_falls_back_to_content(self, classifier):
        result = classifier.classify("application/x-unknown-thing", b"plain text here")
        assert result == FileType.TEXT  # Content detection fallback


class TestDuplicateNameResolution:
    @pytest.fixture
    def classifier(self):
        return FileClassifier()

    def test_first_file_gets_clean_name(self, classifier):
        path = classifier.resolve_local_path("documents", "report.txt", "id1", {})
        assert path == "documents/report.txt"

    def test_duplicate_gets_id_suffix(self, classifier):
        existing = {"id0": {"local_path": "documents/report.txt"}}
        path = classifier.resolve_local_path("documents", "report.txt", "id1", existing)
        assert path == "documents/report (id1).txt"

    def test_cached_path_is_stable(self, classifier):
        existing = {"id1": {"local_path": "documents/report (id1).txt"}}
        path = classifier.resolve_local_path("documents", "report.txt", "id1", existing)
        assert path == "documents/report (id1).txt"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_classifier.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `classifier.py`**

```python
# src/gdrive_backup/classifier.py
"""File type classification using MIME types and content detection."""

import logging
import os
import re
from enum import Enum
from pathlib import Path
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class FileType(Enum):
    TEXT = "text"
    BINARY = "binary"
    UNKNOWN = "unknown"


# MIME types we know are text
TEXT_MIME_PREFIXES = ("text/",)
TEXT_MIME_EXACT = {
    "application/json",
    "application/xml",
    "application/javascript",
    "application/x-javascript",
    "application/ecmascript",
    "application/x-yaml",
    "application/yaml",
    "application/x-sh",
    "application/x-csh",
    "application/sql",
    "application/graphql",
    "application/ld+json",
    "application/xhtml+xml",
    "application/x-httpd-php",
    "application/x-perl",
    "application/x-python",
    "application/x-ruby",
    "application/toml",
    "application/rtf",
    "application/atom+xml",
    "application/rss+xml",
    "application/svg+xml",
    "application/mathml+xml",
}

# MIME types we know are binary
BINARY_MIME_PREFIXES = ("image/", "video/", "audio/")
BINARY_MIME_EXACT = {
    "application/pdf",
    "application/zip",
    "application/gzip",
    "application/x-tar",
    "application/x-7z-compressed",
    "application/x-rar-compressed",
    "application/octet-stream",
    "application/x-bzip2",
    "application/java-archive",
    "application/wasm",
    "application/x-sqlite3",
    # Microsoft Office
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "application/msword",
    "application/vnd.ms-excel",
    "application/vnd.ms-powerpoint",
    # Google native types (exported to Office = binary)
    "application/vnd.google-apps.document",
    "application/vnd.google-apps.spreadsheet",
    "application/vnd.google-apps.presentation",
    "application/vnd.google-apps.drawing",
}

# Characters not allowed in file names
UNSAFE_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def sanitize_filename(name: str) -> str:
    """Sanitize a filename to prevent path traversal and invalid characters.

    Args:
        name: Original file name from Google Drive.

    Returns:
        Safe file name string.
    """
    if not name:
        return "unnamed_file"

    # Remove path traversal components
    name = name.replace("\x00", "")
    # Replace ".." path components but preserve ".." within filenames like "my..file"
    parts = name.split("/")
    parts = [p for p in parts if p != ".."]
    name = "/".join(parts)

    # Strip leading slashes / backslashes
    name = name.lstrip("/\\")

    # Replace unsafe characters
    name = UNSAFE_CHARS.sub("_", name)

    # Ensure non-empty
    name = name.strip()
    if not name:
        return "unnamed_file"

    return name


class FileClassifier:
    """Classifies files as text or binary using MIME type and content detection."""

    def classify_by_mime(self, mime_type: str) -> FileType:
        """Classify a file based on its MIME type.

        Returns FileType.UNKNOWN if the MIME type is not recognized.
        """
        if not mime_type:
            return FileType.UNKNOWN

        # Check exact matches first
        if mime_type in TEXT_MIME_EXACT:
            return FileType.TEXT
        if mime_type in BINARY_MIME_EXACT:
            return FileType.BINARY

        # Check prefixes
        for prefix in TEXT_MIME_PREFIXES:
            if mime_type.startswith(prefix):
                return FileType.TEXT
        for prefix in BINARY_MIME_PREFIXES:
            if mime_type.startswith(prefix):
                return FileType.BINARY

        return FileType.UNKNOWN

    def classify_by_content(self, content: bytes) -> FileType:
        """Classify a file based on its content using python-magic.

        Falls back to heuristic check if python-magic is unavailable.
        """
        try:
            import magic
            detected = magic.from_buffer(content[:8192], mime=True)
            logger.debug(f"Content detection: {detected}")
            result = self.classify_by_mime(detected)
            if result != FileType.UNKNOWN:
                return result
        except ImportError:
            logger.debug("python-magic not available, using heuristic")
        except Exception as e:
            logger.debug(f"Content detection failed: {e}")

        # Heuristic fallback: check for null bytes
        sample = content[:8192]
        if b"\x00" in sample:
            return FileType.BINARY
        return FileType.TEXT

    def classify(self, mime_type: str, content: Optional[bytes] = None) -> FileType:
        """Classify a file using MIME type first, then content detection as fallback.

        Args:
            mime_type: MIME type from Google Drive API.
            content: File content bytes for fallback detection.

        Returns:
            FileType.TEXT or FileType.BINARY.
        """
        result = self.classify_by_mime(mime_type)
        if result != FileType.UNKNOWN:
            logger.debug(f"Classified by MIME ({mime_type}): {result.value}")
            return result

        if content is not None:
            result = self.classify_by_content(content)
            logger.debug(f"Classified by content: {result.value}")
            return result

        # Default to binary if we can't determine
        logger.debug(f"Unknown MIME type ({mime_type}), defaulting to binary")
        return FileType.BINARY

    def resolve_local_path(
        self,
        folder_path: str,
        filename: str,
        file_id: str,
        file_cache: Dict[str, dict],
    ) -> str:
        """Resolve local file path, handling duplicate names.

        Args:
            folder_path: Folder path relative to backup root.
            filename: Sanitized file name.
            file_id: Google Drive file ID.
            file_cache: Current file cache {id: {local_path: ...}}.

        Returns:
            Relative local path string.
        """
        filename = sanitize_filename(filename)

        # If this file already has a cached path, use it
        if file_id in file_cache and "local_path" in file_cache[file_id]:
            return file_cache[file_id]["local_path"]

        candidate = f"{folder_path}/{filename}" if folder_path else filename

        # Check if another file already uses this path
        for fid, entry in file_cache.items():
            if fid != file_id and entry.get("local_path") == candidate:
                # Duplicate — add file ID suffix
                stem, ext = os.path.splitext(filename)
                candidate = f"{folder_path}/{stem} ({file_id}){ext}" if folder_path else f"{stem} ({file_id}){ext}"
                break

        return candidate
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_classifier.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/classifier.py tests/test_classifier.py
git commit -m "feat: file classifier with MIME + content detection and path sanitization"
```

---

## Task 7: Git Manager

**Files:**
- Create: `src/gdrive_backup/git_manager.py`
- Create: `tests/test_git_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_git_manager.py
"""Tests for git repository operations."""

import os
from pathlib import Path

import pytest
from git import Repo

from gdrive_backup.git_manager import GitManager, GitError


class TestGitManager:
    @pytest.fixture
    def repo_dir(self, tmp_path):
        d = tmp_path / "repo"
        d.mkdir()
        return d

    @pytest.fixture
    def manager(self, repo_dir):
        return GitManager.init_repo(repo_dir)

    def test_init_repo_creates_git_directory(self, repo_dir):
        manager = GitManager.init_repo(repo_dir)
        assert (repo_dir / ".git").exists()

    def test_init_repo_existing_repo(self, repo_dir):
        GitManager.init_repo(repo_dir)
        # Should not raise on existing repo
        manager = GitManager.init_repo(repo_dir)
        assert manager is not None

    def test_add_file(self, manager, repo_dir):
        # Write a file
        test_file = repo_dir / "test.txt"
        test_file.write_text("hello")

        manager.add_file("test.txt")
        # File should be staged
        assert "test.txt" in [item.a_path for item in manager._repo.index.diff("HEAD")] or \
               len(manager._repo.untracked_files) == 0  # After add, not untracked

    def test_write_and_add_file(self, manager, repo_dir):
        manager.write_file("subdir/test.txt", b"content here")
        assert (repo_dir / "subdir" / "test.txt").read_bytes() == b"content here"

    def test_remove_file(self, manager, repo_dir):
        # Create and commit a file first
        manager.write_file("to_delete.txt", b"delete me")
        manager.commit("add file")

        manager.remove_file("to_delete.txt")
        assert not (repo_dir / "to_delete.txt").exists()

    def test_move_file(self, manager, repo_dir):
        manager.write_file("old_name.txt", b"content")
        manager.commit("add file")

        manager.move_file("old_name.txt", "new_name.txt")
        assert not (repo_dir / "old_name.txt").exists()
        assert (repo_dir / "new_name.txt").read_bytes() == b"content"

    def test_commit_creates_commit(self, manager, repo_dir):
        manager.write_file("file.txt", b"data")
        sha = manager.commit("test commit")
        assert sha is not None
        assert len(sha) == 40

    def test_commit_with_no_changes_returns_none(self, manager):
        # Initial commit to establish HEAD
        manager.write_file("init.txt", b"init")
        manager.commit("initial")
        # No changes — should return None
        result = manager.commit("empty commit")
        assert result is None

    def test_rejects_symlinks(self, manager, repo_dir):
        # Create a symlink
        target = repo_dir / "real.txt"
        target.write_text("real")
        link = repo_dir / "link.txt"
        link.symlink_to(target)

        with pytest.raises(GitError, match="symlink"):
            manager.add_file("link.txt")

    def test_rejects_path_outside_repo(self, manager):
        with pytest.raises(GitError, match="outside"):
            manager.write_file("../escape.txt", b"bad")

    def test_file_permissions_are_644(self, manager, repo_dir):
        manager.write_file("secure.txt", b"data")
        mode = (repo_dir / "secure.txt").stat().st_mode & 0o777
        assert mode == 0o644
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_git_manager.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `git_manager.py`**

```python
# src/gdrive_backup/git_manager.py
"""Git repository operations for text file backup."""

import logging
import os
import stat
from pathlib import Path
from typing import Optional

from git import Repo, InvalidGitRepositoryError

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Raised when git operations fail."""


class GitManager:
    """Manages a git repository for text file backup."""

    def __init__(self, repo: Repo, repo_path: Path):
        self._repo = repo
        self._path = repo_path

    @classmethod
    def init_repo(cls, path: Path) -> "GitManager":
        """Initialize or open a git repo at the given path.

        Args:
            path: Directory for the git repo.

        Returns:
            GitManager instance.
        """
        path.mkdir(parents=True, exist_ok=True)
        try:
            repo = Repo(path)
            logger.debug(f"Opened existing git repo at {path}")
        except InvalidGitRepositoryError:
            repo = Repo.init(path)
            logger.info(f"Initialized new git repo at {path}")
        return cls(repo, path)

    def write_file(self, relative_path: str, content: bytes) -> None:
        """Write content to a file and stage it.

        Args:
            relative_path: Path relative to repo root.
            content: File content bytes.

        Raises:
            GitError: If path escapes the repo.
        """
        self._validate_path(relative_path)
        full_path = self._path / relative_path

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        os.chmod(full_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

        self._repo.index.add([relative_path])
        logger.debug(f"Wrote and staged: {relative_path}")

    def add_file(self, relative_path: str) -> None:
        """Stage an existing file.

        Args:
            relative_path: Path relative to repo root.

        Raises:
            GitError: If path is a symlink or invalid.
        """
        full_path = self._path / relative_path
        if full_path.is_symlink():
            raise GitError(f"Refusing to add symlink: {relative_path}")

        self._validate_path(relative_path)
        self._repo.index.add([relative_path])
        logger.debug(f"Staged: {relative_path}")

    def remove_file(self, relative_path: str) -> None:
        """Remove a file from the repo and staging area.

        Args:
            relative_path: Path relative to repo root.
        """
        self._validate_path(relative_path)
        full_path = self._path / relative_path

        if full_path.exists():
            self._repo.index.remove([relative_path], working_tree=True)
            logger.debug(f"Removed: {relative_path}")
        else:
            logger.warning(f"File not found for removal: {relative_path}")

    def move_file(self, old_path: str, new_path: str) -> None:
        """Move/rename a file in the repo.

        Args:
            old_path: Current relative path.
            new_path: New relative path.
        """
        self._validate_path(old_path)
        self._validate_path(new_path)

        old_full = self._path / old_path
        new_full = self._path / new_path

        if not old_full.exists():
            logger.warning(f"Source file not found for move: {old_path}")
            return

        new_full.parent.mkdir(parents=True, exist_ok=True)
        self._repo.index.move([old_path, new_path])
        logger.debug(f"Moved: {old_path} → {new_path}")

    def commit(self, message: str) -> Optional[str]:
        """Create a commit with all staged changes.

        Args:
            message: Commit message.

        Returns:
            Commit SHA hex string, or None if nothing to commit.
        """
        if not self._has_changes():
            logger.debug("No changes to commit")
            return None

        commit = self._repo.index.commit(message)
        logger.info(f"Committed: {message} ({commit.hexsha[:8]})")
        return commit.hexsha

    def _has_changes(self) -> bool:
        """Check if there are staged changes to commit."""
        if not self._repo.head.is_valid():
            # No commits yet — check if index has entries
            return len(self._repo.index.entries) > 0

        diff = self._repo.index.diff("HEAD")
        return len(diff) > 0

    def _validate_path(self, relative_path: str) -> None:
        """Validate that a path doesn't escape the repo root."""
        resolved = (self._path / relative_path).resolve()
        if not str(resolved).startswith(str(self._path.resolve())):
            raise GitError(f"Path escapes repo root (outside): {relative_path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_git_manager.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/git_manager.py tests/test_git_manager.py
git commit -m "feat: git manager for text file backup with security validation"
```

---

## Task 8: Mirror Manager

**Files:**
- Create: `src/gdrive_backup/mirror_manager.py`
- Create: `tests/test_mirror_manager.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_mirror_manager.py
"""Tests for binary file mirror operations."""

import os
from pathlib import Path

import pytest

from gdrive_backup.mirror_manager import MirrorManager, MirrorError


class TestMirrorManager:
    @pytest.fixture
    def mirror(self, mirror_dir):
        return MirrorManager(mirror_dir)

    def test_write_file_creates_with_content(self, mirror, mirror_dir):
        mirror.write_file("photos/cat.jpg", b"\x89PNG fake image data")
        assert (mirror_dir / "photos" / "cat.jpg").read_bytes() == b"\x89PNG fake image data"

    def test_write_file_creates_subdirectories(self, mirror, mirror_dir):
        mirror.write_file("a/b/c/deep.pdf", b"pdf data")
        assert (mirror_dir / "a" / "b" / "c" / "deep.pdf").exists()

    def test_write_file_sets_644_permissions(self, mirror, mirror_dir):
        mirror.write_file("doc.pdf", b"data")
        mode = (mirror_dir / "doc.pdf").stat().st_mode & 0o777
        assert mode == 0o644

    def test_write_file_atomic(self, mirror, mirror_dir):
        # Write initial content
        mirror.write_file("doc.pdf", b"version 1")
        # Overwrite — should be atomic (write to temp, then move)
        mirror.write_file("doc.pdf", b"version 2")
        assert (mirror_dir / "doc.pdf").read_bytes() == b"version 2"

    def test_delete_file(self, mirror, mirror_dir):
        mirror.write_file("to_delete.jpg", b"data")
        mirror.delete_file("to_delete.jpg")
        assert not (mirror_dir / "to_delete.jpg").exists()

    def test_delete_nonexistent_no_error(self, mirror):
        mirror.delete_file("does_not_exist.jpg")  # Should not raise

    def test_delete_cleans_empty_parents(self, mirror, mirror_dir):
        mirror.write_file("a/b/only_file.jpg", b"data")
        mirror.delete_file("a/b/only_file.jpg")
        assert not (mirror_dir / "a" / "b").exists()

    def test_move_file(self, mirror, mirror_dir):
        mirror.write_file("old/file.jpg", b"data")
        mirror.move_file("old/file.jpg", "new/file.jpg")
        assert not (mirror_dir / "old" / "file.jpg").exists()
        assert (mirror_dir / "new" / "file.jpg").read_bytes() == b"data"

    def test_rejects_path_outside_mirror(self, mirror):
        with pytest.raises(MirrorError, match="outside"):
            mirror.write_file("../../escape.txt", b"bad")

    def test_rejects_symlinks(self, mirror, mirror_dir):
        target = mirror_dir / "real.txt"
        target.write_text("real")
        link_path = "link.txt"
        (mirror_dir / link_path).symlink_to(target)

        with pytest.raises(MirrorError, match="symlink"):
            mirror.write_file(link_path, b"overwrite via symlink")

    def test_file_exists(self, mirror, mirror_dir):
        assert not mirror.file_exists("nope.jpg")
        mirror.write_file("yes.jpg", b"data")
        assert mirror.file_exists("yes.jpg")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mirror_manager.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `mirror_manager.py`**

```python
# src/gdrive_backup/mirror_manager.py
"""Binary file mirror directory operations."""

import logging
import os
import stat
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class MirrorError(Exception):
    """Raised when mirror operations fail."""


class MirrorManager:
    """Manages the binary file mirror directory."""

    def __init__(self, mirror_path: Path):
        self._path = mirror_path.resolve()
        self._path.mkdir(parents=True, exist_ok=True)

    def write_file(self, relative_path: str, content: bytes) -> None:
        """Write content to a file atomically.

        Downloads to a temp file first, then moves into place.

        Args:
            relative_path: Path relative to mirror root.
            content: File content bytes.

        Raises:
            MirrorError: If path escapes mirror or targets a symlink.
        """
        self._validate_path(relative_path)
        full_path = self._path / relative_path

        if full_path.exists() and full_path.is_symlink():
            raise MirrorError(f"Refusing to overwrite symlink: {relative_path}")

        full_path.parent.mkdir(parents=True, exist_ok=True)

        # Atomic write: temp file + rename
        fd, tmp_path = tempfile.mkstemp(dir=full_path.parent)
        fd_closed = False
        try:
            os.write(fd, content)
            os.close(fd)
            fd_closed = True
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            os.replace(tmp_path, full_path)
        except Exception:
            if not fd_closed:
                os.close(fd)
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise

        logger.debug(f"Wrote mirror file: {relative_path} ({len(content)} bytes)")

    def delete_file(self, relative_path: str) -> None:
        """Delete a file from the mirror.

        Also cleans up empty parent directories.

        Args:
            relative_path: Path relative to mirror root.
        """
        full_path = self._path / relative_path

        if not full_path.exists():
            logger.debug(f"Mirror file not found for deletion: {relative_path}")
            return

        full_path.unlink()
        logger.debug(f"Deleted mirror file: {relative_path}")

        # Clean up empty parent directories
        parent = full_path.parent
        while parent != self._path:
            try:
                parent.rmdir()  # Only succeeds if empty
                parent = parent.parent
            except OSError:
                break

    def move_file(self, old_path: str, new_path: str) -> None:
        """Move/rename a file in the mirror.

        Args:
            old_path: Current relative path.
            new_path: New relative path.
        """
        self._validate_path(old_path)
        self._validate_path(new_path)

        old_full = self._path / old_path
        new_full = self._path / new_path

        if not old_full.exists():
            logger.warning(f"Source not found for move: {old_path}")
            return

        new_full.parent.mkdir(parents=True, exist_ok=True)
        os.replace(old_full, new_full)
        logger.debug(f"Moved mirror file: {old_path} → {new_path}")

        # Clean up empty parent directories of old path
        parent = old_full.parent
        while parent != self._path:
            try:
                parent.rmdir()
                parent = parent.parent
            except OSError:
                break

    def file_exists(self, relative_path: str) -> bool:
        """Check if a file exists in the mirror."""
        return (self._path / relative_path).exists()

    def _validate_path(self, relative_path: str) -> None:
        """Validate that a path doesn't escape the mirror root."""
        resolved = (self._path / relative_path).resolve()
        if not str(resolved).startswith(str(self._path)):
            raise MirrorError(f"Path escapes mirror root (outside): {relative_path}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mirror_manager.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/mirror_manager.py tests/test_mirror_manager.py
git commit -m "feat: mirror manager for binary file backup with atomic writes"
```

---

## Task 9: Sync Engine

**Files:**
- Create: `src/gdrive_backup/sync_engine.py`
- Create: `tests/test_sync_engine.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_sync_engine.py
"""Tests for backup sync engine."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gdrive_backup.classifier import FileClassifier, FileType
from gdrive_backup.drive_client import DriveFile, DriveChange
from gdrive_backup.sync_engine import SyncEngine, SyncStats, SyncError


def _make_drive_file(
    id="f1", name="test.txt", mime="text/plain",
    parents=None, md5="abc", size=100,
    modified="2026-01-01T00:00:00Z"
):
    return DriveFile(
        id=id, name=name, mime_type=mime,
        parents=parents or ["root"],
        md5=md5, size=size, modified_time=modified,
    )


class TestSyncEngine:
    @pytest.fixture
    def mock_drive(self):
        return MagicMock()

    @pytest.fixture
    def mock_git(self):
        return MagicMock()

    @pytest.fixture
    def mock_mirror(self):
        return MagicMock()

    @pytest.fixture
    def mock_classifier(self):
        clf = MagicMock()
        clf.classify.return_value = FileType.TEXT
        clf.resolve_local_path.side_effect = lambda folder, name, fid, cache: f"{folder}/{name}" if folder else name
        return clf

    @pytest.fixture
    def state_file(self, tmp_path):
        return tmp_path / "state.json"

    @pytest.fixture
    def engine(self, mock_drive, mock_git, mock_mirror, mock_classifier, state_file):
        return SyncEngine(
            drive_client=mock_drive,
            git_manager=mock_git,
            mirror_manager=mock_mirror,
            classifier=mock_classifier,
            state_file=state_file,
            max_file_size_mb=0,
        )

    def test_full_scan_downloads_and_routes_text_file(self, engine, mock_drive, mock_git):
        file = _make_drive_file()
        mock_drive.list_all_files.return_value = iter([file])
        mock_drive.get_start_page_token.return_value = "token1"
        mock_drive.download_file.return_value = b"hello"
        mock_drive.resolve_file_path.return_value = ""

        stats = engine.run_full_scan()

        mock_git.write_file.assert_called_once()
        assert stats.added == 1

    def test_full_scan_routes_binary_to_mirror(self, engine, mock_drive, mock_mirror, mock_classifier):
        file = _make_drive_file(mime="image/png", name="photo.png")
        mock_drive.list_all_files.return_value = iter([file])
        mock_drive.get_start_page_token.return_value = "token1"
        mock_drive.download_file.return_value = b"\x89PNG"
        mock_drive.resolve_file_path.return_value = ""
        mock_classifier.classify.return_value = FileType.BINARY

        stats = engine.run_full_scan()

        mock_mirror.write_file.assert_called_once()
        assert stats.added == 1

    def test_full_scan_exports_google_native(self, engine, mock_drive, mock_mirror, mock_classifier):
        file = _make_drive_file(
            mime="application/vnd.google-apps.document",
            name="My Doc",
        )
        mock_drive.list_all_files.return_value = iter([file])
        mock_drive.get_start_page_token.return_value = "token1"
        mock_drive.export_file.return_value = b"docx content"
        mock_drive.resolve_file_path.return_value = ""
        mock_classifier.classify.return_value = FileType.BINARY

        stats = engine.run_full_scan()

        mock_drive.export_file.assert_called_once()
        mock_mirror.write_file.assert_called_once()

    def test_full_scan_skips_large_files(self, engine, mock_drive):
        engine._max_file_size_bytes = 100  # 100 bytes limit
        file = _make_drive_file(size=200)
        mock_drive.list_all_files.return_value = iter([file])
        mock_drive.get_start_page_token.return_value = "token1"

        stats = engine.run_full_scan()

        assert stats.skipped == 1
        mock_drive.download_file.assert_not_called()

    def test_full_scan_saves_state(self, engine, mock_drive, state_file):
        mock_drive.list_all_files.return_value = iter([])
        mock_drive.get_start_page_token.return_value = "token1"

        engine.run_full_scan()

        state = json.loads(state_file.read_text())
        assert state["start_page_token"] == "token1"

    def test_incremental_sync_processes_changes(self, engine, mock_drive, mock_git, state_file):
        # Set up existing state
        state_file.write_text(json.dumps({
            "start_page_token": "old_token",
            "last_run": "2026-01-01T00:00:00Z",
            "last_run_status": "success",
            "file_cache": {},
        }))

        file = _make_drive_file()
        change = DriveChange(file_id="f1", removed=False, file=file)
        mock_drive.get_changes.return_value = ([change], "new_token")
        mock_drive.download_file.return_value = b"content"
        mock_drive.resolve_file_path.return_value = ""

        stats = engine.run_incremental()

        assert stats.added == 1

    def test_incremental_sync_handles_deletions(self, engine, mock_drive, mock_git, mock_mirror, state_file):
        state_file.write_text(json.dumps({
            "start_page_token": "old_token",
            "last_run": "2026-01-01T00:00:00Z",
            "last_run_status": "success",
            "file_cache": {
                "f1": {"type": "text", "local_path": "test.txt"},
            },
        }))

        change = DriveChange(file_id="f1", removed=True, file=None)
        mock_drive.get_changes.return_value = ([change], "new_token")

        stats = engine.run_incremental()

        mock_git.remove_file.assert_called_once_with("test.txt")
        assert stats.deleted == 1

    def test_run_auto_selects_mode(self, engine, state_file):
        # No state file — should do full scan
        with patch.object(engine, "run_full_scan", return_value=SyncStats()) as mock_full:
            engine.run()
            mock_full.assert_called_once()

    def test_run_auto_selects_incremental(self, engine, state_file):
        state_file.write_text(json.dumps({
            "start_page_token": "token",
            "last_run": "2026-01-01T00:00:00Z",
            "last_run_status": "success",
            "file_cache": {},
        }))
        with patch.object(engine, "run_incremental", return_value=SyncStats()) as mock_inc:
            engine.run()
            mock_inc.assert_called_once()

    def test_file_failure_doesnt_stop_run(self, engine, mock_drive, mock_git):
        file1 = _make_drive_file(id="f1", name="good.txt")
        file2 = _make_drive_file(id="f2", name="bad.txt")
        file3 = _make_drive_file(id="f3", name="also_good.txt")

        mock_drive.list_all_files.return_value = iter([file1, file2, file3])
        mock_drive.get_start_page_token.return_value = "token1"
        mock_drive.download_file.side_effect = [b"good", Exception("network error"), b"also good"]
        mock_drive.resolve_file_path.return_value = ""

        stats = engine.run_full_scan()

        assert stats.added == 2
        assert stats.failed == 1

    def test_corrupt_state_triggers_full_scan(self, engine, state_file):
        state_file.write_text("{{invalid json")
        with patch.object(engine, "run_full_scan", return_value=SyncStats()) as mock_full:
            engine.run()
            mock_full.assert_called_once()

    def test_move_detection(self, engine, mock_drive, mock_git, mock_classifier, state_file):
        # File was previously at old_path
        state_file.write_text(json.dumps({
            "start_page_token": "old_token",
            "last_run": "2026-01-01T00:00:00Z",
            "last_run_status": "success",
            "file_cache": {
                "f1": {"type": "text", "local_path": "old_folder/test.txt", "md5": "abc"},
            },
        }))

        # File moved to new folder
        file = _make_drive_file(id="f1", name="test.txt", parents=["new_folder_id"])
        change = DriveChange(file_id="f1", removed=False, file=file)
        mock_drive.get_changes.return_value = ([change], "new_token")
        mock_drive.download_file.return_value = b"content"
        mock_drive.resolve_file_path.return_value = "new_folder"
        mock_classifier.classify.return_value = FileType.TEXT

        stats = engine.run_incremental()

        mock_git.move_file.assert_called_once_with("old_folder/test.txt", "new_folder/test.txt")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_sync_engine.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `sync_engine.py`**

```python
# src/gdrive_backup/sync_engine.py
"""Orchestrates the Google Drive backup process."""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gdrive_backup.classifier import FileClassifier, FileType, sanitize_filename
from gdrive_backup.drive_client import DriveClient, DriveFile, GOOGLE_EXPORT_MAP, GOOGLE_EXPORT_EXTENSIONS
from gdrive_backup.git_manager import GitManager
from gdrive_backup.mirror_manager import MirrorManager

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """Raised when sync fails fatally."""


@dataclass
class SyncStats:
    """Statistics for a sync run."""
    added: int = 0
    modified: int = 0
    deleted: int = 0
    skipped: int = 0
    failed: int = 0

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"{self.added} added")
        if self.modified:
            parts.append(f"{self.modified} modified")
        if self.deleted:
            parts.append(f"{self.deleted} deleted")
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        if self.failed:
            parts.append(f"{self.failed} failed")
        return ", ".join(parts) if parts else "no changes"


class SyncEngine:
    """Orchestrates the full backup flow."""

    def __init__(
        self,
        drive_client: DriveClient,
        git_manager: GitManager,
        mirror_manager: MirrorManager,
        classifier: FileClassifier,
        state_file: Path,
        max_file_size_mb: int = 0,
        include_shared: bool = False,
        folder_ids: Optional[list] = None,
    ):
        self._drive = drive_client
        self._git = git_manager
        self._mirror = mirror_manager
        self._classifier = classifier
        self._state_file = state_file
        self._max_file_size_bytes = max_file_size_mb * 1024 * 1024 if max_file_size_mb > 0 else 0
        self._include_shared = include_shared
        self._folder_ids = folder_ids or []
        self._state: dict = {}
        self._file_cache: dict = {}

    def run(self) -> SyncStats:
        """Run a backup — auto-selects full scan or incremental."""
        self._load_state()

        if self._state.get("start_page_token"):
            logger.info("Running incremental backup")
            return self.run_incremental()
        else:
            logger.info("Running full scan (first run)")
            return self.run_full_scan()

    def run_full_scan(self) -> SyncStats:
        """Enumerate all Drive files and download them."""
        stats = SyncStats()
        self._load_state()

        logger.info("Starting full scan...")
        start_token = self._drive.get_start_page_token()

        for drive_file in self._drive.list_all_files(
            include_shared=self._include_shared,
            folder_ids=self._folder_ids if self._folder_ids else None,
        ):
            if drive_file.should_skip:
                logger.debug(f"Skipping non-downloadable: {drive_file.name} ({drive_file.mime_type})")
                continue

            try:
                self._process_file(drive_file, stats)
            except Exception as e:
                logger.error(f"Failed to process {drive_file.name}: {e}")
                stats.failed += 1

        # Commit all text file changes
        commit_msg = f"Backup {datetime.now(timezone.utc).isoformat()} — {stats.summary()}"
        self._git.commit(commit_msg)

        # Save state
        self._state["start_page_token"] = start_token
        self._state["last_run"] = datetime.now(timezone.utc).isoformat()
        self._state["last_run_status"] = "success" if stats.failed == 0 else "partial"
        self._state["file_cache"] = self._file_cache
        self._save_state()

        logger.info(f"Full scan complete: {stats.summary()}")
        return stats

    def run_incremental(self) -> SyncStats:
        """Process only changes since last run."""
        stats = SyncStats()
        self._load_state()

        start_token = self._state.get("start_page_token")
        if not start_token:
            raise SyncError("No start_page_token in state — run a full scan first")

        changes, new_token = self._drive.get_changes(start_token)
        logger.info(f"Processing {len(changes)} changes")

        for change in changes:
            try:
                if change.removed:
                    self._handle_delete(change.file_id, stats)
                elif change.file:
                    if change.file.should_skip:
                        continue
                    is_update = change.file_id in self._file_cache
                    self._process_file(change.file, stats, is_update=is_update)
            except Exception as e:
                logger.error(f"Failed to process change for {change.file_id}: {e}")
                stats.failed += 1

        # Commit text file changes
        if stats.added or stats.modified or stats.deleted:
            commit_msg = f"Backup {datetime.now(timezone.utc).isoformat()} — {stats.summary()}"
            self._git.commit(commit_msg)

        # Save state
        if new_token:
            self._state["start_page_token"] = new_token
        self._state["last_run"] = datetime.now(timezone.utc).isoformat()
        self._state["last_run_status"] = "success" if stats.failed == 0 else "partial"
        self._state["file_cache"] = self._file_cache
        self._save_state()

        logger.info(f"Incremental sync complete: {stats.summary()}")
        return stats

    def _check_disk_space(self, required_bytes: int) -> None:
        """Check if sufficient disk space is available.

        Raises:
            SyncError: If disk space is insufficient.
        """
        for path in [self._git._path if hasattr(self._git, '_path') else None,
                      self._mirror._path if hasattr(self._mirror, '_path') else None]:
            if path and path.exists():
                usage = shutil.disk_usage(path)
                if usage.free < required_bytes + (100 * 1024 * 1024):  # 100MB buffer
                    raise SyncError(
                        f"Insufficient disk space at {path}: "
                        f"{usage.free // (1024*1024)}MB free, "
                        f"need {required_bytes // (1024*1024)}MB + 100MB buffer"
                    )

    def _process_file(self, drive_file: DriveFile, stats: SyncStats, is_update: bool = False) -> None:
        """Download, classify, and route a single file."""
        # Check file size limit
        if self._max_file_size_bytes and drive_file.size and drive_file.size > self._max_file_size_bytes:
            logger.info(f"Skipping large file: {drive_file.name} ({drive_file.size} bytes)")
            stats.skipped += 1
            return

        # Check disk space before downloading
        if drive_file.size:
            self._check_disk_space(drive_file.size)

        # Check if file has actually changed (MD5)
        if not is_update and drive_file.id in self._file_cache:
            cached = self._file_cache[drive_file.id]
            if cached.get("md5") == drive_file.md5 and drive_file.md5:
                logger.debug(f"Unchanged (MD5 match): {drive_file.name}")
                return

        # Download or export
        file_name = drive_file.name
        if drive_file.is_exportable:
            export_mime = drive_file.export_mime_type
            content = self._drive.export_file(drive_file.id, export_mime)
            file_name = f"{drive_file.name}{drive_file.export_extension}"
        else:
            content = self._drive.download_file(drive_file.id)

        # Classify
        file_type = self._classifier.classify(drive_file.mime_type, content)

        # Resolve local path
        folder_path = self._drive.resolve_file_path(drive_file.parents)
        local_path = self._classifier.resolve_local_path(
            folder_path, sanitize_filename(file_name), drive_file.id, self._file_cache
        )

        # Handle move/rename: if cached path differs from new path, move the file
        old_cached = self._file_cache.get(drive_file.id)
        if old_cached and old_cached.get("local_path") and old_cached["local_path"] != local_path:
            old_path = old_cached["local_path"]
            old_type = old_cached.get("type", "binary")
            if old_type == "text":
                self._git.move_file(old_path, local_path)
            else:
                self._mirror.move_file(old_path, local_path)
            logger.info(f"Moved: {old_path} → {local_path}")

        # Route to git or mirror
        if file_type == FileType.TEXT:
            self._git.write_file(local_path, content)
        else:
            self._mirror.write_file(local_path, content)

        # Update cache
        self._file_cache[drive_file.id] = {
            "type": file_type.value,
            "mime": drive_file.mime_type,
            "local_path": local_path,
            "md5": drive_file.md5,
            "last_modified": drive_file.modified_time,
        }

        if is_update:
            stats.modified += 1
            logger.info(f"Updated: {local_path}")
        else:
            stats.added += 1
            logger.info(f"Added: {local_path} → {'git' if file_type == FileType.TEXT else 'mirror'}")

    def _handle_delete(self, file_id: str, stats: SyncStats) -> None:
        """Handle a deleted file."""
        cached = self._file_cache.get(file_id)
        if not cached:
            return

        local_path = cached["local_path"]
        file_type = cached["type"]

        if file_type == "text":
            self._git.remove_file(local_path)
        else:
            self._mirror.delete_file(local_path)

        del self._file_cache[file_id]
        stats.deleted += 1
        logger.info(f"Deleted: {local_path}")

    def _load_state(self) -> None:
        """Load state from state file."""
        if self._state_file.exists():
            try:
                self._state = json.loads(self._state_file.read_text())
                self._file_cache = self._state.get("file_cache", {})
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Corrupt state file, starting fresh: {e}")
                self._state = {}
                self._file_cache = {}
        else:
            self._state = {}
            self._file_cache = {}

    def _save_state(self) -> None:
        """Save state to state file."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(self._state, indent=2))
        logger.debug(f"State saved to {self._state_file}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_sync_engine.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/sync_engine.py tests/test_sync_engine.py
git commit -m "feat: sync engine orchestrating full scan and incremental backup"
```

---

## Task 10: CLI Module

**Files:**
- Create: `src/gdrive_backup/cli.py`
- Create: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `cli.py`**

```python
# src/gdrive_backup/cli.py
"""CLI entry point for gdrive-backup."""

import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

import click
import yaml

from gdrive_backup import __version__
from gdrive_backup.auth import authenticate, build_drive_service, AuthError
from gdrive_backup.classifier import FileClassifier
from gdrive_backup.config import Config, ConfigError, load_config, DEFAULT_CONTROL_DIR
from gdrive_backup.drive_client import DriveClient
from gdrive_backup.git_manager import GitManager
from gdrive_backup.logging_setup import setup_logging
from gdrive_backup.mirror_manager import MirrorManager
from gdrive_backup.sync_engine import SyncEngine

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
@click.option("--config", "config_path", default=None, help="Config file path")
@click.option("-v", "--verbose", is_flag=True, help="Increase log verbosity")
@click.option("--debug", is_flag=True, help="Maximum log verbosity")
@click.option("-q", "--quiet", is_flag=True, help="Suppress console output")
@click.version_option(version=__version__)
@click.pass_context
def main(ctx, config_path, verbose, debug, quiet):
    """Google Drive Backup — back up your Drive to git + mirror."""
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path

    # Determine console log level
    if quiet:
        console_level = "ERROR"
    elif debug:
        console_level = "DEBUG"
    elif verbose:
        console_level = "INFO"
    else:
        console_level = None  # Use config default

    ctx.obj["console_level"] = console_level


@main.command()
@click.pass_context
def init(ctx):
    """Set up a new backup configuration."""
    control_dir = _resolve_control_dir(ctx.obj["config_path"])
    control_dir.mkdir(parents=True, exist_ok=True)
    (control_dir / "logs").mkdir(exist_ok=True)

    config_path = control_dir / "config.yaml"

    if config_path.exists():
        click.echo(f"Config already exists at {config_path}")
        if not click.confirm("Overwrite?"):
            return

    # Auth method
    auth_method = click.prompt(
        "Authentication method",
        type=click.Choice(["oauth", "service_account"]),
        default="oauth",
    )

    # Credentials file
    creds_prompt = "Path to credentials JSON file"
    creds_input = click.prompt(creds_prompt, default=str(control_dir / "credentials.json"))
    creds_path = Path(creds_input).expanduser()

    if not creds_path.exists():
        click.echo(f"Note: Place your credentials file at {creds_path}")

    # Backup paths
    git_repo_path = click.prompt(
        "Git repo path (for text files)",
        default=str(Path.home() / "gdrive-backup-repo"),
    )
    mirror_path = click.prompt(
        "Mirror path (for binary files)",
        default=str(Path.home() / "gdrive-backup-mirror"),
    )

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


@main.command()
@click.pass_context
def run(ctx):
    """Run a single backup."""
    config_path = _resolve_config_path(ctx.obj["config_path"])
    control_dir = _resolve_control_dir(ctx.obj["config_path"])

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
        ctx.obj["console_level"],
    )

    try:
        engine = _build_engine(config)
        stats = engine.run()
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
@click.pass_context
def status(ctx):
    """Show backup status."""
    config_path = _resolve_config_path(ctx.obj["config_path"])
    control_dir = _resolve_control_dir(ctx.obj["config_path"])

    try:
        config = load_config(str(config_path), str(control_dir))
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
@click.pass_context
def config(ctx):
    """Show current configuration."""
    config_path = _resolve_config_path(ctx.obj["config_path"])

    if not config_path.exists():
        click.echo(f"No config file found at {config_path}")
        click.echo("Run 'gdrive-backup init' to create one.")
        return

    click.echo(f"Config file: {config_path}")
    click.echo("---")
    click.echo(config_path.read_text())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/cli.py tests/test_cli.py
git commit -m "feat: CLI with init, run, status, and config commands"
```

---

## Task 11: Daemon Mode

**Files:**
- Create: `src/gdrive_backup/daemon.py`
- Create: `tests/test_daemon.py`

- [ ] **Step 1: Write failing tests**

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_daemon.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement `daemon.py`**

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_daemon.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Add daemon command to CLI**

Add to `src/gdrive_backup/cli.py` — add a `daemon` command after the existing commands:

```python
@main.command()
@click.pass_context
def daemon(ctx):
    """Start continuous backup mode."""
    config_path = _resolve_config_path(ctx.obj["config_path"])
    control_dir = _resolve_control_dir(ctx.obj["config_path"])

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
        ctx.obj["console_level"],
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
```

- [ ] **Step 6: Commit**

```bash
git add src/gdrive_backup/daemon.py tests/test_daemon.py src/gdrive_backup/cli.py
git commit -m "feat: daemon mode with PID file and graceful shutdown"
```

---

## Task 12: Run Full Test Suite & Final Touches

**Files:**
- Modify: various files for any test fixes
- Update: `.gitignore`

- [ ] **Step 1: Run the full test suite**

Run: `cd /home/eyal/repos/google-drive-backup && source .venv/bin/activate && python -m pytest tests/ -v --tb=short`
Expected: All tests PASS.

- [ ] **Step 2: Fix any failing tests**

Address any failures discovered during the full test run.

- [ ] **Step 3: Run test coverage**

Run: `python -m pytest tests/ --cov=gdrive_backup --cov-report=term-missing`
Expected: Coverage report showing per-module coverage.

- [ ] **Step 4: Verify CLI entry point works**

Run: `gdrive-backup --help`
Expected: Shows help text with all commands.

- [ ] **Step 5: Update `.gitignore` if needed**

Ensure `.venv/`, `__pycache__/`, `.eggs/`, `*.egg-info/` are all covered.

- [ ] **Step 6: Final commit**

```bash
git add -A
git commit -m "chore: final test fixes and cleanup"
```

- [ ] **Step 7: Push to GitHub**

```bash
git push origin main
```
