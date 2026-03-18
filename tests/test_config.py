# tests/test_config.py
"""Tests for configuration loading and validation."""

import logging
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
        with caplog.at_level(logging.WARNING, logger="gdrive_backup.config"):
            load_config(str(config_file), str(control_dir))
        assert any("permission" in r.message.lower() for r in caplog.records)


def test_github_config_parsed(tmp_path):
    """GithubConfig is parsed from the github section."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
auth:
  method: oauth
  credentials_file: creds.json
  token_file: token.json
backup:
  git_repo_path: /tmp/repo
  mirror_path: /tmp/mirror
github:
  enabled: true
  pat: "mytoken"
  owner: "alice"
  repo: "backup-data"
  private: true
  auto_create: true
""")
    cfg_file.chmod(0o600)
    config = load_config(str(cfg_file), str(tmp_path))
    assert config.github is not None
    assert config.github.enabled is True
    assert config.github.pat == "mytoken"
    assert config.github.owner == "alice"
    assert config.github.repo == "backup-data"
    assert config.github.private is True
    assert config.github.auto_create is True
    assert config.github.e2e_output_mode is None
    assert config.github.e2e_base_repo is None


def test_github_config_absent(tmp_path):
    """Config without github section has github=None."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
auth:
  method: oauth
  credentials_file: creds.json
  token_file: token.json
backup:
  git_repo_path: /tmp/repo
  mirror_path: /tmp/mirror
""")
    cfg_file.chmod(0o600)
    config = load_config(str(cfg_file), str(tmp_path))
    assert config.github is None


def test_github_config_e2e_new_repo(tmp_path):
    """e2e.output_mode new_repo is accepted."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
auth:
  method: oauth
  credentials_file: creds.json
  token_file: token.json
backup:
  git_repo_path: /tmp/repo
  mirror_path: /tmp/mirror
github:
  enabled: true
  pat: ""
  owner: "alice"
  repo: "backup-data"
  private: true
  auto_create: true
  e2e:
    output_mode: new_repo
""")
    cfg_file.chmod(0o600)
    config = load_config(str(cfg_file), str(tmp_path))
    assert config.github.e2e_output_mode == "new_repo"


def test_github_config_e2e_invalid_mode(tmp_path):
    """Invalid e2e.output_mode raises ConfigError."""
    from gdrive_backup.config import ConfigError
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
auth:
  method: oauth
  credentials_file: creds.json
  token_file: token.json
backup:
  git_repo_path: /tmp/repo
  mirror_path: /tmp/mirror
github:
  enabled: true
  pat: ""
  owner: "alice"
  repo: "backup-data"
  private: true
  auto_create: false
  e2e:
    output_mode: bad_value
""")
    cfg_file.chmod(0o600)
    with pytest.raises(ConfigError, match="e2e.output_mode"):
        load_config(str(cfg_file), str(tmp_path))


def test_github_config_e2e_new_branch_requires_base_repo(tmp_path):
    """new_branch mode without base_repo raises ConfigError."""
    from gdrive_backup.config import ConfigError
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
auth:
  method: oauth
  credentials_file: creds.json
  token_file: token.json
backup:
  git_repo_path: /tmp/repo
  mirror_path: /tmp/mirror
github:
  enabled: true
  pat: ""
  owner: "alice"
  repo: "backup-data"
  private: true
  auto_create: false
  e2e:
    output_mode: new_branch
""")
    cfg_file.chmod(0o600)
    with pytest.raises(ConfigError, match="base_repo"):
        load_config(str(cfg_file), str(tmp_path))
