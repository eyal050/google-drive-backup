# tests/test_e2e.py
"""Mock-based end-to-end test: real SyncEngine + GitManager + MirrorManager,
mock DriveClient. No real Drive credentials needed."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gdrive_backup.classifier import FileClassifier
from gdrive_backup.drive_client import DriveChange, DriveFile
from gdrive_backup.git_manager import GitManager
from gdrive_backup.mirror_manager import MirrorManager
from gdrive_backup.sync_engine import SyncEngine


def _make_drive_file(file_id, name, mime_type, size=100):
    """Create a DriveFile with the 7 required dataclass fields."""
    return DriveFile(
        id=file_id,
        name=name,
        mime_type=mime_type,
        parents=[],
        md5=None,
        size=size,
        modified_time="2024-01-01T00:00:00Z",
    )


@pytest.fixture
def e2e_setup(tmp_path):
    git_path = tmp_path / "repo"
    mirror_path = tmp_path / "mirror"
    state_file = tmp_path / "state.json"

    git_manager = GitManager.init_repo(git_path)
    mirror_manager = MirrorManager(mirror_path)
    classifier = FileClassifier()

    mock_drive = MagicMock()
    mock_drive.get_start_page_token.return_value = "token-001"
    mock_drive.resolve_file_path.return_value = ""

    engine = SyncEngine(
        drive_client=mock_drive,
        git_manager=git_manager,
        mirror_manager=mirror_manager,
        classifier=classifier,
        state_file=state_file,
        max_file_size_mb=0,
        include_shared=False,
        folder_ids=[],
    )

    text_file = _make_drive_file("f1", "notes.txt", "text/plain", size=50)
    binary_file = _make_drive_file("f2", "photo.jpg", "image/jpeg", size=200)

    return {
        "engine": engine,
        "mock_drive": mock_drive,
        "git_path": git_path,
        "mirror_path": mirror_path,
        "state_file": state_file,
        "text_file": text_file,
        "binary_file": binary_file,
    }


def test_full_scan_routes_files_correctly(e2e_setup):
    """Full scan places text files in git repo and binary files in mirror."""
    s = e2e_setup
    s["mock_drive"].list_all_files.return_value = [s["text_file"], s["binary_file"]]
    s["mock_drive"].download_file.return_value = b"hello text"

    stats = s["engine"].run_full_scan()

    assert stats.added == 2
    assert stats.failed == 0

    git_files = list(s["git_path"].rglob("*.txt"))
    assert len(git_files) == 1
    assert git_files[0].read_bytes() == b"hello text"

    mirror_files = list(s["mirror_path"].rglob("*.jpg"))
    assert len(mirror_files) == 1

    assert s["state_file"].exists()
    state = json.loads(s["state_file"].read_text())
    assert "start_page_token" in state
    assert len(state["file_cache"]) == 2


def test_full_scan_creates_git_commit(e2e_setup):
    """Full scan commits text file changes to git."""
    s = e2e_setup
    s["mock_drive"].list_all_files.return_value = [s["text_file"]]
    s["mock_drive"].download_file.return_value = b"content"

    s["engine"].run_full_scan()

    commits = list(s["engine"]._git._repo.iter_commits())
    assert len(commits) >= 1
    assert "Backup" in commits[0].message


def test_incremental_adds_new_file(e2e_setup):
    """Incremental run picks up a newly added file."""
    s = e2e_setup

    s["mock_drive"].list_all_files.return_value = [s["text_file"]]
    s["mock_drive"].download_file.return_value = b"original"
    s["engine"].run_full_scan()

    new_file = _make_drive_file("f3", "doc.pdf", "application/pdf", size=300)
    change = DriveChange(file_id="f3", removed=False, file=new_file)
    s["mock_drive"].get_changes.return_value = ([change], "token-002")
    s["mock_drive"].download_file.return_value = b"pdf bytes"

    stats = s["engine"].run_incremental()

    assert stats.added == 1
    assert stats.failed == 0
    mirror_files = list(s["mirror_path"].rglob("*.pdf"))
    assert len(mirror_files) == 1


def test_incremental_handles_deletion(e2e_setup):
    """Incremental run removes a file that was deleted on Drive."""
    s = e2e_setup

    s["mock_drive"].list_all_files.return_value = [s["text_file"]]
    s["mock_drive"].download_file.return_value = b"to be deleted"
    s["engine"].run_full_scan()

    del_change = DriveChange(file_id="f1", removed=True, file=None)
    s["mock_drive"].get_changes.return_value = ([del_change], "token-003")

    stats = s["engine"].run_incremental()

    assert stats.deleted == 1
    git_files = list(s["git_path"].rglob("*.txt"))
    assert len(git_files) == 0
