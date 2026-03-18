# tests/test_git_manager.py
"""Tests for git repository operations."""

import os
from pathlib import Path

import pytest
from git import Repo

from gdrive_backup.git_manager import GitManager, GitError


class TestGitManager:
    @pytest.fixture
    def repo_dir(self, tmp_path):
        d = tmp_path / "repo"
        d.mkdir()
        return d

    @pytest.fixture
    def manager(self, repo_dir):
        return GitManager.init_repo(repo_dir)

    def test_init_repo_creates_git_directory(self, repo_dir):
        manager = GitManager.init_repo(repo_dir)
        assert (repo_dir / ".git").exists()

    def test_init_repo_existing_repo(self, repo_dir):
        GitManager.init_repo(repo_dir)
        # Should not raise on existing repo
        manager = GitManager.init_repo(repo_dir)
        assert manager is not None

    def test_add_file(self, manager, repo_dir):
        # Write a file
        test_file = repo_dir / "test.txt"
        test_file.write_text("hello")

        manager.add_file("test.txt")
        # File should be staged (not in untracked files after add)
        assert "test.txt" not in manager._repo.untracked_files

    def test_write_and_add_file(self, manager, repo_dir):
        manager.write_file("subdir/test.txt", b"content here")
        assert (repo_dir / "subdir" / "test.txt").read_bytes() == b"content here"

    def test_remove_file(self, manager, repo_dir):
        # Create and commit a file first
        manager.write_file("to_delete.txt", b"delete me")
        manager.commit("add file")

        manager.remove_file("to_delete.txt")
        assert not (repo_dir / "to_delete.txt").exists()

    def test_move_file(self, manager, repo_dir):
        manager.write_file("old_name.txt", b"content")
        manager.commit("add file")

        manager.move_file("old_name.txt", "new_name.txt")
        assert not (repo_dir / "old_name.txt").exists()
        assert (repo_dir / "new_name.txt").read_bytes() == b"content"

    def test_commit_creates_commit(self, manager, repo_dir):
        manager.write_file("file.txt", b"data")
        sha = manager.commit("test commit")
        assert sha is not None
        assert len(sha) == 40

    def test_commit_with_no_changes_returns_none(self, manager):
        # Initial commit to establish HEAD
        manager.write_file("init.txt", b"init")
        manager.commit("initial")
        # No changes — should return None
        result = manager.commit("empty commit")
        assert result is None

    def test_rejects_symlinks(self, manager, repo_dir):
        # Create a symlink
        target = repo_dir / "real.txt"
        target.write_text("real")
        link = repo_dir / "link.txt"
        link.symlink_to(target)

        with pytest.raises(GitError, match="symlink"):
            manager.add_file("link.txt")

    def test_rejects_path_outside_repo(self, manager):
        with pytest.raises(GitError, match="outside"):
            manager.write_file("../escape.txt", b"bad")

    def test_file_permissions_are_644(self, manager, repo_dir):
        manager.write_file("secure.txt", b"data")
        mode = (repo_dir / "secure.txt").stat().st_mode & 0o777
        assert mode == 0o644

    def test_set_remote_adds_new(self, manager):
        manager.set_remote("origin", "https://github.com/alice/repo.git")
        assert "origin" in [r.name for r in manager._repo.remotes]
        assert manager._repo.remote("origin").url == "https://github.com/alice/repo.git"

    def test_set_remote_updates_url(self, manager):
        manager.set_remote("origin", "https://github.com/alice/repo.git")
        manager.set_remote("origin", "https://github.com/alice/other.git")
        assert manager._repo.remote("origin").url == "https://github.com/alice/other.git"

    def test_remove_remote_removes(self, manager):
        manager.set_remote("origin", "https://github.com/alice/repo.git")
        manager.remove_remote("origin")
        assert "origin" not in [r.name for r in manager._repo.remotes]

    def test_remove_remote_noop_if_absent(self, manager):
        # Should not raise
        manager.remove_remote("nonexistent")

    def test_push_raises_when_no_remote(self, manager):
        with pytest.raises(GitError, match="not found"):
            manager.push(remote="origin", branch="main")
