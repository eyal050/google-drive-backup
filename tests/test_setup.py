"""Unit tests for scripts/setup.py credential validation."""

import json
import sys
from pathlib import Path

import pytest

# Import validate_credentials_json directly from the script file.
# Use an absolute path so this works regardless of the working directory
# when pytest is invoked (e.g. from a subdirectory or IDE plugin).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from setup import validate_credentials_json


def write_json(tmp_path, data):
    p = tmp_path / "creds.json"
    p.write_text(json.dumps(data))
    return p


def test_valid_desktop_app_credential(tmp_path):
    p = write_json(tmp_path, {"installed": {"client_id": "x", "client_secret": "y"}})
    ok, msg = validate_credentials_json(p)
    assert ok is True
    assert msg == ""


def test_file_not_found(tmp_path):
    ok, msg = validate_credentials_json(tmp_path / "missing.json")
    assert ok is False
    assert "not found" in msg.lower()


def test_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("not json {{{")
    ok, msg = validate_credentials_json(p)
    assert ok is False
    assert "invalid json" in msg.lower()


def test_web_credential(tmp_path):
    p = write_json(tmp_path, {"web": {"client_id": "x"}})
    ok, msg = validate_credentials_json(p)
    assert ok is False
    assert "web application" in msg.lower() or "desktop app" in msg.lower()


def test_service_account_credential(tmp_path):
    p = write_json(tmp_path, {"type": "service_account", "project_id": "proj"})
    ok, msg = validate_credentials_json(p)
    assert ok is False
    assert "service account" in msg.lower()


def test_unrecognized_format(tmp_path):
    p = write_json(tmp_path, {"something_else": {}})
    ok, msg = validate_credentials_json(p)
    assert ok is False
    assert "unrecognized" in msg.lower() or "installed" in msg.lower()
