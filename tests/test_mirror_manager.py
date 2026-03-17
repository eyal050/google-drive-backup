# tests/test_mirror_manager.py
"""Tests for binary file mirror operations."""

import os
from pathlib import Path

import pytest

from gdrive_backup.mirror_manager import MirrorManager, MirrorError


class TestMirrorManager:
    @pytest.fixture
    def mirror(self, mirror_dir):
        return MirrorManager(mirror_dir)

    def test_write_file_creates_with_content(self, mirror, mirror_dir):
        mirror.write_file("photos/cat.jpg", b"\x89PNG fake image data")
        assert (mirror_dir / "photos" / "cat.jpg").read_bytes() == b"\x89PNG fake image data"

    def test_write_file_creates_subdirectories(self, mirror, mirror_dir):
        mirror.write_file("a/b/c/deep.pdf", b"pdf data")
        assert (mirror_dir / "a" / "b" / "c" / "deep.pdf").exists()

    def test_write_file_sets_644_permissions(self, mirror, mirror_dir):
        mirror.write_file("doc.pdf", b"data")
        mode = (mirror_dir / "doc.pdf").stat().st_mode & 0o777
        assert mode == 0o644

    def test_write_file_atomic(self, mirror, mirror_dir):
        # Write initial content
        mirror.write_file("doc.pdf", b"version 1")
        # Overwrite — should be atomic (write to temp, then move)
        mirror.write_file("doc.pdf", b"version 2")
        assert (mirror_dir / "doc.pdf").read_bytes() == b"version 2"

    def test_delete_file(self, mirror, mirror_dir):
        mirror.write_file("to_delete.jpg", b"data")
        mirror.delete_file("to_delete.jpg")
        assert not (mirror_dir / "to_delete.jpg").exists()

    def test_delete_nonexistent_no_error(self, mirror):
        mirror.delete_file("does_not_exist.jpg")  # Should not raise

    def test_delete_cleans_empty_parents(self, mirror, mirror_dir):
        mirror.write_file("a/b/only_file.jpg", b"data")
        mirror.delete_file("a/b/only_file.jpg")
        assert not (mirror_dir / "a" / "b").exists()

    def test_move_file(self, mirror, mirror_dir):
        mirror.write_file("old/file.jpg", b"data")
        mirror.move_file("old/file.jpg", "new/file.jpg")
        assert not (mirror_dir / "old" / "file.jpg").exists()
        assert (mirror_dir / "new" / "file.jpg").read_bytes() == b"data"

    def test_move_nonexistent_no_error(self, mirror):
        mirror.move_file("does_not_exist.jpg", "dest.jpg")  # Should not raise

    def test_rejects_symlink_target(self, mirror, mirror_dir):
        # Create a symlink target
        target = mirror_dir / "real_target.jpg"
        target.write_bytes(b"real data")
        link_path = "link.jpg"
        (mirror_dir / link_path).symlink_to(target)

        with pytest.raises(MirrorError, match="symlink"):
            mirror.write_file(link_path, b"overwrite via symlink")

    def test_file_exists(self, mirror, mirror_dir):
        assert not mirror.file_exists("nope.jpg")
        mirror.write_file("yes.jpg", b"data")
        assert mirror.file_exists("yes.jpg")
