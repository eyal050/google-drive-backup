# tests/test_sync_engine.py
"""Tests for backup sync engine."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from gdrive_backup.classifier import FileClassifier, FileType
from gdrive_backup.drive_client import DriveFile, DriveChange
from gdrive_backup.sync_engine import SyncEngine, SyncStats, SyncError


def _make_drive_file(
    id="f1", name="test.txt", mime="text/plain",
    parents=None, md5="abc", size=100,
    modified="2026-01-01T00:00:00Z"
):
    return DriveFile(
        id=id, name=name, mime_type=mime,
        parents=parents or ["root"],
        md5=md5, size=size, modified_time=modified,
    )


class TestSyncEngine:
    @pytest.fixture
    def mock_drive(self):
        return MagicMock()

    @pytest.fixture
    def mock_git(self):
        return MagicMock()

    @pytest.fixture
    def mock_mirror(self):
        return MagicMock()

    @pytest.fixture
    def mock_classifier(self):
        clf = MagicMock()
        clf.classify.return_value = FileType.TEXT
        clf.resolve_local_path.side_effect = lambda folder, name, fid, cache: f"{folder}/{name}" if folder else name
        return clf

    @pytest.fixture
    def state_file(self, tmp_path):
        return tmp_path / "state.json"

    @pytest.fixture
    def engine(self, mock_drive, mock_git, mock_mirror, mock_classifier, state_file):
        return SyncEngine(
            drive_client=mock_drive,
            git_manager=mock_git,
            mirror_manager=mock_mirror,
            classifier=mock_classifier,
            state_file=state_file,
            max_file_size_mb=0,
        )

    def test_full_scan_downloads_and_routes_text_file(self, engine, mock_drive, mock_git):
        file = _make_drive_file()
        mock_drive.list_all_files.return_value = iter([file])
        mock_drive.get_start_page_token.return_value = "token1"
        mock_drive.download_file.return_value = b"hello"
        mock_drive.resolve_file_path.return_value = ""

        stats = engine.run_full_scan()

        mock_git.write_file.assert_called_once()
        assert stats.added == 1

    def test_full_scan_routes_binary_to_mirror(self, engine, mock_drive, mock_mirror, mock_classifier):
        file = _make_drive_file(mime="image/png", name="photo.png")
        mock_drive.list_all_files.return_value = iter([file])
        mock_drive.get_start_page_token.return_value = "token1"
        mock_drive.download_file.return_value = b"\x89PNG"
        mock_drive.resolve_file_path.return_value = ""
        mock_classifier.classify.return_value = FileType.BINARY

        stats = engine.run_full_scan()

        mock_mirror.write_file.assert_called_once()
        assert stats.added == 1

    def test_full_scan_exports_google_native(self, engine, mock_drive, mock_mirror, mock_classifier):
        file = _make_drive_file(
            mime="application/vnd.google-apps.document",
            name="My Doc",
        )
        mock_drive.list_all_files.return_value = iter([file])
        mock_drive.get_start_page_token.return_value = "token1"
        mock_drive.export_file.return_value = b"docx content"
        mock_drive.resolve_file_path.return_value = ""
        mock_classifier.classify.return_value = FileType.BINARY

        stats = engine.run_full_scan()

        mock_drive.export_file.assert_called_once()
        mock_mirror.write_file.assert_called_once()

    def test_full_scan_skips_large_files(self, engine, mock_drive):
        engine._max_file_size_bytes = 100  # 100 bytes limit
        file = _make_drive_file(size=200)
        mock_drive.list_all_files.return_value = iter([file])
        mock_drive.get_start_page_token.return_value = "token1"

        stats = engine.run_full_scan()

        assert stats.skipped == 1
        mock_drive.download_file.assert_not_called()

    def test_full_scan_saves_state(self, engine, mock_drive, state_file):
        mock_drive.list_all_files.return_value = iter([])
        mock_drive.get_start_page_token.return_value = "token1"

        engine.run_full_scan()

        state = json.loads(state_file.read_text())
        assert state["start_page_token"] == "token1"

    def test_incremental_sync_processes_changes(self, engine, mock_drive, mock_git, state_file):
        # Set up existing state
        state_file.write_text(json.dumps({
            "start_page_token": "old_token",
            "last_run": "2026-01-01T00:00:00Z",
            "last_run_status": "success",
            "file_cache": {},
        }))

        file = _make_drive_file()
        change = DriveChange(file_id="f1", removed=False, file=file)
        mock_drive.get_changes.return_value = ([change], "new_token")
        mock_drive.download_file.return_value = b"content"
        mock_drive.resolve_file_path.return_value = ""

        stats = engine.run_incremental()

        assert stats.added == 1

    def test_incremental_sync_handles_deletions(self, engine, mock_drive, mock_git, mock_mirror, state_file):
        state_file.write_text(json.dumps({
            "start_page_token": "old_token",
            "last_run": "2026-01-01T00:00:00Z",
            "last_run_status": "success",
            "file_cache": {
                "f1": {"type": "text", "local_path": "test.txt"},
            },
        }))

        change = DriveChange(file_id="f1", removed=True, file=None)
        mock_drive.get_changes.return_value = ([change], "new_token")

        stats = engine.run_incremental()

        mock_git.remove_file.assert_called_once_with("test.txt")
        assert stats.deleted == 1

    def test_run_auto_selects_mode(self, engine, state_file):
        # No state file — should do full scan
        with patch.object(engine, "run_full_scan", return_value=SyncStats()) as mock_full:
            engine.run()
            mock_full.assert_called_once()

    def test_run_auto_selects_incremental(self, engine, state_file):
        state_file.write_text(json.dumps({
            "start_page_token": "token",
            "last_run": "2026-01-01T00:00:00Z",
            "last_run_status": "success",
            "file_cache": {},
        }))
        with patch.object(engine, "run_incremental", return_value=SyncStats()) as mock_inc:
            engine.run()
            mock_inc.assert_called_once()

    def test_file_failure_doesnt_stop_run(self, engine, mock_drive, mock_git):
        file1 = _make_drive_file(id="f1", name="good.txt")
        file2 = _make_drive_file(id="f2", name="bad.txt")
        file3 = _make_drive_file(id="f3", name="also_good.txt")

        mock_drive.list_all_files.return_value = iter([file1, file2, file3])
        mock_drive.get_start_page_token.return_value = "token1"
        mock_drive.download_file.side_effect = [b"good", Exception("network error"), b"also good"]
        mock_drive.resolve_file_path.return_value = ""

        stats = engine.run_full_scan()

        assert stats.added == 2
        assert stats.failed == 1

    def test_corrupt_state_triggers_full_scan(self, engine, state_file):
        state_file.write_text("{{invalid json")
        with patch.object(engine, "run_full_scan", return_value=SyncStats()) as mock_full:
            engine.run()
            mock_full.assert_called_once()

    def test_move_detection(self, engine, mock_drive, mock_git, mock_classifier, state_file):
        # File was previously at old_path
        state_file.write_text(json.dumps({
            "start_page_token": "old_token",
            "last_run": "2026-01-01T00:00:00Z",
            "last_run_status": "success",
            "file_cache": {
                "f1": {"type": "text", "local_path": "old_folder/test.txt", "md5": "abc"},
            },
        }))

        # File moved to new folder
        file = _make_drive_file(id="f1", name="test.txt", parents=["new_folder_id"])
        change = DriveChange(file_id="f1", removed=False, file=file)
        mock_drive.get_changes.return_value = ([change], "new_token")
        mock_drive.download_file.return_value = b"content"
        mock_drive.resolve_file_path.return_value = "new_folder"
        mock_classifier.classify.return_value = FileType.TEXT

        stats = engine.run_incremental()

        mock_git.move_file.assert_called_once_with("old_folder/test.txt", "new_folder/test.txt")
