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
