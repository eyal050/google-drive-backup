#!/usr/bin/env python3
"""GCP credential guide and setup handoff for gdrive-backup."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

CONTROL_DIR = Path.home() / ".gdrive-backup"

GCP_INSTRUCTIONS = """
Google Cloud Console Setup
==========================

Before you can use gdrive-backup, you need Google OAuth credentials.
Follow these steps (takes about 2 minutes):

  1. Open the Google Cloud Console and create or select a project:
     https://console.cloud.google.com/

  2. Enable the Google Drive API:
     https://console.cloud.google.com/apis/library/drive.googleapis.com
     → Click "Enable"

  3. Create OAuth 2.0 credentials:
     https://console.cloud.google.com/apis/credentials
     → Create Credentials → OAuth client ID
     → Application type: Desktop app
     → Name it anything (e.g. "gdrive-backup")
     → Click Create, then Download JSON

  4. Note the path to the downloaded file — you will enter it below.

"""


def validate_credentials_json(path: Path) -> tuple[bool, str]:
    """Validate a Google OAuth Desktop app credentials JSON file.

    Returns (ok, error_message). error_message is empty string when ok=True.
    """
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
            "  Go back to https://console.cloud.google.com/apis/credentials\n"
            "  and create a new OAuth client ID with Application type: Desktop app"
        )

    if data.get("type") == "service_account":
        return False, (
            "This is a service account key, not an OAuth credential.\n"
            "  Service account setup is not supported by this wizard.\n"
            "  Run 'gdrive-backup init' manually for service account setup."
        )

    return False, (
        "Unrecognized credentials format. Expected a Desktop app OAuth credential\n"
        "  (the JSON file should contain an 'installed' key)."
    )
