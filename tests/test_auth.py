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
