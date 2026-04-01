#!/usr/bin/env python3
"""DEPRECATED - use 'gdrive-backup init' directly.

This script is kept for backwards compatibility with older install.sh URLs.
"""
import subprocess
import sys


def main():
    print("Note: scripts/setup.py is deprecated. Running 'gdrive-backup init' instead.\n")
    result = subprocess.run(["gdrive-backup", "init"], check=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
