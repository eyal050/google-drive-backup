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
