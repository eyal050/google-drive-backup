# src/gdrive_backup/git_manager.py
"""Git repository operations for text file backup."""

import logging
import os
import stat
from pathlib import Path
from typing import Optional

from git import Repo, InvalidGitRepositoryError

logger = logging.getLogger(__name__)


class GitError(Exception):
    """Raised when git operations fail."""


class GitManager:
    """Manages a git repository for text file backup."""

    def __init__(self, repo: Repo, repo_path: Path):
        self._repo = repo
        self._path = repo_path

    @classmethod
    def init_repo(cls, path: Path) -> "GitManager":
        """Initialize or open a git repo at the given path.

        Args:
            path: Directory for the git repo.

        Returns:
            GitManager instance.
        """
        path.mkdir(parents=True, exist_ok=True)
        try:
            repo = Repo(path)
            logger.debug(f"Opened existing git repo at {path}")
        except InvalidGitRepositoryError:
            repo = Repo.init(path)
            logger.info(f"Initialized new git repo at {path}")
        return cls(repo, path)

    def write_file(self, relative_path: str, content: bytes) -> None:
        """Write content to a file and stage it.

        Args:
            relative_path: Path relative to repo root.
            content: File content bytes.

        Raises:
            GitError: If path escapes the repo.
        """
        self._validate_path(relative_path)
        full_path = self._path / relative_path

        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        os.chmod(full_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)

        self._repo.index.add([relative_path])
        logger.debug(f"Wrote and staged: {relative_path}")

    def add_file(self, relative_path: str) -> None:
        """Stage an existing file.

        Args:
            relative_path: Path relative to repo root.

        Raises:
            GitError: If path is a symlink or invalid.
        """
        full_path = self._path / relative_path
        if full_path.is_symlink():
            raise GitError(f"Refusing to add symlink: {relative_path}")

        self._validate_path(relative_path)
        self._repo.index.add([relative_path])
        logger.debug(f"Staged: {relative_path}")

    def remove_file(self, relative_path: str) -> None:
        """Remove a file from the repo and staging area.

        Args:
            relative_path: Path relative to repo root.
        """
        self._validate_path(relative_path)
        full_path = self._path / relative_path

        if full_path.exists():
            self._repo.index.remove([relative_path], working_tree=True)
            logger.debug(f"Removed: {relative_path}")
        else:
            logger.warning(f"File not found for removal: {relative_path}")

    def move_file(self, old_path: str, new_path: str) -> None:
        """Move/rename a file in the repo.

        Args:
            old_path: Current relative path.
            new_path: New relative path.
        """
        self._validate_path(old_path)
        self._validate_path(new_path)

        old_full = self._path / old_path
        new_full = self._path / new_path

        if not old_full.exists():
            logger.warning(f"Source file not found for move: {old_path}")
            return

        new_full.parent.mkdir(parents=True, exist_ok=True)
        self._repo.index.move([old_path, new_path])
        logger.debug(f"Moved: {old_path} → {new_path}")

    def commit(self, message: str) -> Optional[str]:
        """Create a commit with all staged changes.

        Args:
            message: Commit message.

        Returns:
            Commit SHA hex string, or None if nothing to commit.
        """
        if not self._has_changes():
            logger.debug("No changes to commit")
            return None

        commit = self._repo.index.commit(message)
        logger.info(f"Committed: {message} ({commit.hexsha[:8]})")
        return commit.hexsha

    def _has_changes(self) -> bool:
        """Check if there are staged changes to commit."""
        if not self._repo.head.is_valid():
            # No commits yet — check if index has entries
            return len(self._repo.index.entries) > 0

        diff = self._repo.index.diff("HEAD")
        return len(diff) > 0

    def set_remote(self, name: str, url: str) -> None:
        """Add a remote or update its URL if it already exists."""
        try:
            remote = self._repo.remote(name)
            if remote.url != url:
                self._repo.delete_remote(remote)
                self._repo.create_remote(name, url)
                logger.debug(f"Updated remote '{name}' URL")
            else:
                logger.debug(f"Remote '{name}' URL unchanged")
        except ValueError:
            self._repo.create_remote(name, url)
            logger.debug(f"Added remote '{name}'")

    def remove_remote(self, name: str) -> None:
        """Remove a remote if it exists; silently does nothing if absent."""
        try:
            remote = self._repo.remote(name)
            self._repo.delete_remote(remote)
            logger.debug(f"Removed remote '{name}'")
        except ValueError:
            pass  # already absent

    def push(self, remote: str = "origin", branch: str = "main") -> None:
        """Push HEAD to remote/branch.

        Args:
            remote: Name of the git remote.
            branch: Remote branch name to push to (HEAD:refs/heads/{branch}).

        Raises:
            GitError: If the remote does not exist or push fails.
        """
        try:
            r = self._repo.remote(remote)
        except ValueError:
            raise GitError(f"Remote '{remote}' not found")

        refspec = f"HEAD:refs/heads/{branch}"
        try:
            push_infos = r.push(refspec=refspec)
        except Exception as e:
            raise GitError(f"Push to '{remote}/{branch}' failed: {e}") from e

        for info in push_infos:
            if info.flags & info.ERROR:
                raise GitError(f"Push to '{remote}/{branch}' failed: {info.summary}")

        logger.info(f"Pushed HEAD to {remote}/{branch}")

    def _validate_path(self, relative_path: str) -> None:
        """Validate that a path doesn't escape the repo root."""
        resolved = (self._path / relative_path).resolve()
        if not str(resolved).startswith(str(self._path.resolve())):
            raise GitError(f"Path escapes repo root (outside): {relative_path}")
