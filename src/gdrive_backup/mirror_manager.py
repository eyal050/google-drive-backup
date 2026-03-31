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
        try:
            self._path.mkdir(parents=True, exist_ok=True)
            logger.debug(f"Mirror directory ready: {self._path}")
        except OSError as e:
            raise MirrorError(f"Cannot create mirror directory {mirror_path}: {e}") from e

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

        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise MirrorError(f"Failed to create parent directories for {relative_path}: {e}") from e

        # Atomic write: temp file + rename
        fd = None
        tmp_path = None
        try:
            fd, tmp_path = tempfile.mkstemp(dir=full_path.parent)
            os.write(fd, content)
            os.close(fd)
            fd = None  # Mark as closed
            os.chmod(tmp_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            os.replace(tmp_path, full_path)
            tmp_path = None  # Mark as moved (no cleanup needed)
        except Exception as e:
            raise MirrorError(f"Failed to write mirror file {relative_path}: {e}") from e
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if tmp_path is not None:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

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

        try:
            full_path.unlink()
            logger.debug(f"Deleted mirror file: {relative_path}")
        except OSError as e:
            logger.error(f"Failed to delete mirror file {relative_path}: {e}")
            return

        # Clean up empty parent directories
        parent = full_path.parent
        while parent != self._path:
            try:
                parent.rmdir()  # Only succeeds if empty
                logger.debug(f"Removed empty directory: {parent}")
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

        try:
            new_full.parent.mkdir(parents=True, exist_ok=True)
            os.replace(old_full, new_full)
            logger.debug(f"Moved mirror file: {old_path} -> {new_path}")
        except OSError as e:
            raise MirrorError(f"Failed to move mirror file {old_path} -> {new_path}: {e}") from e

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
