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
