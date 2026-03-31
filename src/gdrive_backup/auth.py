# src/gdrive_backup/auth.py
"""OAuth 2.0 and service account authentication for Google Drive API."""

import logging
import os
import stat
import sys
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from google.auth.credentials import Credentials
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials as OAuthCredentials
from google.oauth2 import service_account
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

# Timeout for the OAuth local-server callback (seconds)
OAUTH_TIMEOUT_SECONDS = 120


class AuthError(Exception):
    """Raised when authentication fails."""


def _is_wsl() -> bool:
    """Detect if running inside WSL (Windows Subsystem for Linux)."""
    try:
        with open("/proc/version", "r") as f:
            return "microsoft" in f.read().lower()
    except (OSError, IOError):
        return False


def _is_headless() -> bool:
    """Detect if running without a display (headless / SSH / container)."""
    if os.environ.get("DISPLAY"):
        return False
    if os.environ.get("WAYLAND_DISPLAY"):
        return False
    # WSL2 often has no DISPLAY but can open Windows browser
    return not _is_wsl()


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
    logger.info(f"Authenticating with method={method}")
    logger.debug(f"Credentials file: {credentials_file}")
    logger.debug(f"Token file: {token_file}")

    if method == "oauth":
        try:
            _validate_credentials_file(credentials_file)
        except AuthError as e:
            logger.error(f"Credentials file validation failed: {e}")
            raise
        return _oauth_flow(credentials_file, token_file)
    elif method == "service_account":
        try:
            _validate_credentials_file(credentials_file)
        except AuthError as e:
            logger.error(f"Credentials file validation failed: {e}")
            raise
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
    logger.debug("Building Google Drive API service")
    try:
        service = build("drive", "v3", credentials=credentials)
        logger.info("Google Drive API service built successfully")
        return service
    except Exception as e:
        logger.error(f"Failed to build Drive API service: {e}")
        raise AuthError(f"Failed to build Drive API service: {e}") from e


def _oauth_flow(credentials_file: Path, token_file: Path) -> Credentials:
    """Run OAuth 2.0 flow with token caching."""
    creds = None

    # Step 1: Try loading cached token
    if token_file.exists():
        logger.debug(f"Found cached token file: {token_file}")
        try:
            creds = OAuthCredentials.from_authorized_user_file(str(token_file), SCOPES)
            logger.debug(f"Cached token loaded (valid={creds.valid}, expired={creds.expired})")
        except Exception as e:
            logger.warning(f"Failed to load cached token: {e}")
            creds = None
    else:
        logger.debug(f"No cached token file at {token_file}")

    # Step 2: Return if valid
    if creds and creds.valid:
        logger.info("Using valid cached OAuth token")
        return creds

    # Step 3: Try refreshing expired token
    if creds and creds.expired and creds.refresh_token:
        logger.info("Attempting to refresh expired OAuth token")
        try:
            creds.refresh(Request())
            logger.info("OAuth token refreshed successfully")
            _save_token(creds, token_file)
            return creds
        except Exception as e:
            logger.warning(f"Token refresh failed: {e}. Will start new OAuth flow.")
            creds = None

    # Step 4: Run new OAuth consent flow
    wsl = _is_wsl()
    headless = _is_headless()
    logger.info(f"Starting new OAuth consent flow (WSL={wsl}, headless={headless})")

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
    except Exception as e:
        raise AuthError(f"Failed to load client secrets from {credentials_file}: {e}") from e

    if wsl or headless:
        # WSL2: localhost redirect from Windows browser won't reach WSL2.
        # Headless: no browser at all.
        # Use paste-the-redirect-URL flow instead.
        logger.info("Using paste-redirect-URL flow (WSL2 or headless)")
        try:
            creds = _paste_redirect_oauth_flow(flow)
        except Exception as e:
            raise AuthError(f"OAuth flow failed: {e}") from e
    else:
        # Native Linux/Mac with display: use local server + browser
        try:
            creds = flow.run_local_server(
                port=0,
                open_browser=True,
                timeout_seconds=OAUTH_TIMEOUT_SECONDS,
            )
        except Exception as e:
            error_msg = str(e)
            logger.warning(f"Local server OAuth flow failed: {error_msg}")
            logger.info("Falling back to paste-redirect-URL flow")
            try:
                creds = _paste_redirect_oauth_flow(flow)
            except Exception as e2:
                raise AuthError(
                    f"OAuth flow failed. Local server error: {error_msg}. "
                    f"Paste-URL flow error: {e2}"
                ) from e2

    if not creds:
        raise AuthError("OAuth flow completed but no credentials were returned")

    logger.info("OAuth consent flow completed successfully")
    _save_token(creds, token_file)
    return creds


# Redirect URI for the paste-URL flow — a localhost URI that won't actually
# be listening, but Google will redirect to it with the auth code in the URL.
_PASTE_REDIRECT_URI = "http://localhost:1"


def _paste_redirect_oauth_flow(flow: InstalledAppFlow) -> Credentials:
    """OAuth flow for WSL2/headless: user pastes the redirect URL after authorizing.

    Google redirects to http://localhost:1/?code=...&scope=... which fails
    in the browser (nothing is listening), but the URL in the address bar
    contains the authorization code. The user copies that URL and pastes it here.
    """
    flow.redirect_uri = _PASTE_REDIRECT_URI
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

    print(
        "\n╔══════════════════════════════════════════════════════════════╗",
        file=sys.stderr,
    )
    print(
        "║  Open this URL in your browser and authorize the app:      ║",
        file=sys.stderr,
    )
    print(
        "╚══════════════════════════════════════════════════════════════╝",
        file=sys.stderr,
    )
    print(f"\n  {auth_url}\n", file=sys.stderr)
    print(
        "After authorizing, the browser will show a connection error.",
        file=sys.stderr,
    )
    print(
        "That's expected! Copy the FULL URL from the browser address bar",
        file=sys.stderr,
    )
    print(
        "and paste it below.\n",
        file=sys.stderr,
    )

    try:
        redirect_response = input("Paste the redirect URL here: ").strip()
    except (EOFError, KeyboardInterrupt):
        raise AuthError("Authorization cancelled by user")

    if not redirect_response:
        raise AuthError("No URL provided")

    # Parse the authorization code from the redirect URL
    code = _extract_code_from_url(redirect_response)
    logger.debug("Authorization code extracted from redirect URL")

    try:
        flow.fetch_token(code=code)
    except Exception as e:
        raise AuthError(f"Failed to exchange authorization code for token: {e}") from e

    return flow.credentials


def _extract_code_from_url(url: str) -> str:
    """Extract the 'code' query parameter from a redirect URL."""
    try:
        parsed = urlparse(url)
        params = parse_qs(parsed.query)
        codes = params.get("code")
        if codes:
            return codes[0]
    except Exception as e:
        logger.debug(f"URL parsing failed: {e}")

    # Maybe the user pasted just the code itself
    if url and "?" not in url and "&" not in url and "/" not in url:
        return url

    raise AuthError(
        "Could not extract authorization code from the URL. "
        "Make sure you copied the FULL URL from your browser's address bar."
    )


def _service_account_flow(credentials_file: Path) -> Credentials:
    """Authenticate using a service account key file."""
    logger.info(f"Authenticating with service account: {credentials_file}")
    try:
        creds = service_account.Credentials.from_service_account_file(
            str(credentials_file), scopes=SCOPES
        )
        logger.info("Authenticated with service account successfully")
        return creds
    except Exception as e:
        logger.error(f"Service account auth failed: {e}")
        raise AuthError(f"Service account auth failed: {e}") from e


def _save_token(creds: Credentials, token_file: Path) -> None:
    """Save OAuth token to file with secure permissions."""
    logger.debug(f"Saving OAuth token to {token_file}")
    try:
        token_file.parent.mkdir(parents=True, exist_ok=True)
        with open(token_file, "w") as f:
            f.write(creds.to_json())
        _set_secure_permissions(token_file)
        logger.info(f"Token saved to {token_file}")
    except Exception as e:
        logger.error(f"Failed to save token to {token_file}: {e}")
        raise AuthError(f"Failed to save OAuth token: {e}") from e


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
    logger.debug(f"Credentials file validated: {path} (permissions {oct(mode & 0o777)})")


def _set_secure_permissions(path: Path) -> None:
    """Set file permissions to owner-only (600)."""
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
