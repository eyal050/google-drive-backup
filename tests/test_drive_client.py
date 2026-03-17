# tests/test_drive_client.py
"""Tests for Google Drive API client wrapper."""

import time
from unittest.mock import MagicMock, patch, call

import pytest

from gdrive_backup.drive_client import (
    DriveClient,
    DriveFile,
    DriveChange,
    RateLimiter,
)


class TestRateLimiter:
    def test_allows_requests_under_limit(self):
        limiter = RateLimiter(max_per_second=100)
        # Should not block for a single request
        start = time.monotonic()
        limiter.wait()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    def test_reduce_rate(self):
        limiter = RateLimiter(max_per_second=100)
        limiter.reduce_rate()
        assert limiter.max_per_second == 50


class TestDriveClient:
    @pytest.fixture
    def mock_service(self):
        return MagicMock()

    @pytest.fixture
    def client(self, mock_service):
        return DriveClient(mock_service)

    def test_list_all_files_paginates(self, client, mock_service):
        # First page returns files + nextPageToken
        page1 = {"files": [{"id": "1", "name": "a.txt", "mimeType": "text/plain",
                            "parents": ["root"], "md5Checksum": "abc", "size": "100",
                            "modifiedTime": "2026-01-01T00:00:00Z"}],
                 "nextPageToken": "token2"}
        page2 = {"files": [{"id": "2", "name": "b.txt", "mimeType": "text/plain",
                            "parents": ["root"], "md5Checksum": "def", "size": "200",
                            "modifiedTime": "2026-01-02T00:00:00Z"}]}

        mock_list = mock_service.files.return_value.list
        mock_list.return_value.execute.side_effect = [page1, page2]

        files = list(client.list_all_files())
        assert len(files) == 2
        assert files[0].id == "1"
        assert files[1].id == "2"

    def test_get_start_page_token(self, client, mock_service):
        mock_service.changes.return_value.getStartPageToken.return_value.execute.return_value = {
            "startPageToken": "12345"
        }
        token = client.get_start_page_token()
        assert token == "12345"

    def test_get_changes(self, client, mock_service):
        response = {
            "changes": [
                {"fileId": "1", "removed": False, "file": {
                    "id": "1", "name": "a.txt", "mimeType": "text/plain",
                    "parents": ["root"], "md5Checksum": "abc", "size": "100",
                    "modifiedTime": "2026-01-01T00:00:00Z", "trashed": False
                }}
            ],
            "newStartPageToken": "99999",
        }
        mock_service.changes.return_value.list.return_value.execute.return_value = response

        changes, new_token = client.get_changes("12345")
        assert len(changes) == 1
        assert changes[0].file_id == "1"
        assert changes[0].removed is False
        assert new_token == "99999"

    def test_download_file(self, client, mock_service):
        mock_request = MagicMock()
        mock_service.files.return_value.get_media.return_value = mock_request

        with patch("gdrive_backup.drive_client.MediaIoBaseDownload") as mock_dl:
            mock_dl_instance = MagicMock()
            mock_dl.return_value = mock_dl_instance
            mock_dl_instance.next_chunk.side_effect = [
                (MagicMock(progress=MagicMock(return_value=0.5)), False),
                (MagicMock(progress=MagicMock(return_value=1.0)), True),
            ]
            content = client.download_file("file_id_1")
            assert content is not None

    def test_export_file(self, client, mock_service):
        mock_request = MagicMock()
        mock_service.files.return_value.export_media.return_value = mock_request

        with patch("gdrive_backup.drive_client.MediaIoBaseDownload") as mock_dl:
            mock_dl_instance = MagicMock()
            mock_dl.return_value = mock_dl_instance
            mock_dl_instance.next_chunk.return_value = (
                MagicMock(progress=MagicMock(return_value=1.0)), True
            )
            content = client.export_file("file_id_1", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            assert content is not None

    def test_resolve_file_path(self, client, mock_service):
        # Mock folder hierarchy: root -> folder1 -> file
        mock_get = mock_service.files.return_value.get
        mock_get.return_value.execute.side_effect = [
            {"name": "folder1", "parents": ["root_id"]},
            {"name": "My Drive", "parents": []},
        ]
        path = client.resolve_file_path(["folder1_id"])
        assert "folder1" in path
