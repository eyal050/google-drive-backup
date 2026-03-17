# src/gdrive_backup/sync_engine.py
"""Orchestrates the Google Drive backup process."""

import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from gdrive_backup.classifier import FileClassifier, FileType, sanitize_filename
from gdrive_backup.drive_client import DriveClient, DriveFile, GOOGLE_EXPORT_MAP, GOOGLE_EXPORT_EXTENSIONS
from gdrive_backup.git_manager import GitManager
from gdrive_backup.mirror_manager import MirrorManager

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """Raised when sync fails fatally."""


@dataclass
class SyncStats:
    """Statistics for a sync run."""
    added: int = 0
    modified: int = 0
    deleted: int = 0
    skipped: int = 0
    failed: int = 0

    def summary(self) -> str:
        parts = []
        if self.added:
            parts.append(f"{self.added} added")
        if self.modified:
            parts.append(f"{self.modified} modified")
        if self.deleted:
            parts.append(f"{self.deleted} deleted")
        if self.skipped:
            parts.append(f"{self.skipped} skipped")
        if self.failed:
            parts.append(f"{self.failed} failed")
        return ", ".join(parts) if parts else "no changes"


class SyncEngine:
    """Orchestrates the full backup flow."""

    def __init__(
        self,
        drive_client: DriveClient,
        git_manager: GitManager,
        mirror_manager: MirrorManager,
        classifier: FileClassifier,
        state_file: Path,
        max_file_size_mb: int = 0,
        include_shared: bool = False,
        folder_ids: Optional[list] = None,
    ):
        self._drive = drive_client
        self._git = git_manager
        self._mirror = mirror_manager
        self._classifier = classifier
        self._state_file = state_file
        self._max_file_size_bytes = max_file_size_mb * 1024 * 1024 if max_file_size_mb > 0 else 0
        self._include_shared = include_shared
        self._folder_ids = folder_ids or []
        self._state: dict = {}
        self._file_cache: dict = {}

    def run(self) -> SyncStats:
        """Run a backup — auto-selects full scan or incremental."""
        self._load_state()

        if self._state.get("start_page_token"):
            logger.info("Running incremental backup")
            return self.run_incremental()
        else:
            logger.info("Running full scan (first run)")
            return self.run_full_scan()

    def run_full_scan(self) -> SyncStats:
        """Enumerate all Drive files and download them."""
        stats = SyncStats()
        self._load_state()

        logger.info("Starting full scan...")
        start_token = self._drive.get_start_page_token()

        for drive_file in self._drive.list_all_files(
            include_shared=self._include_shared,
            folder_ids=self._folder_ids if self._folder_ids else None,
        ):
            if drive_file.should_skip:
                logger.debug(f"Skipping non-downloadable: {drive_file.name} ({drive_file.mime_type})")
                continue

            try:
                self._process_file(drive_file, stats)
            except Exception as e:
                logger.error(f"Failed to process {drive_file.name}: {e}")
                stats.failed += 1

        # Commit all text file changes
        commit_msg = f"Backup {datetime.now(timezone.utc).isoformat()} — {stats.summary()}"
        self._git.commit(commit_msg)

        # Save state
        self._state["start_page_token"] = start_token
        self._state["last_run"] = datetime.now(timezone.utc).isoformat()
        self._state["last_run_status"] = "success" if stats.failed == 0 else "partial"
        self._state["file_cache"] = self._file_cache
        self._save_state()

        logger.info(f"Full scan complete: {stats.summary()}")
        return stats

    def run_incremental(self) -> SyncStats:
        """Process only changes since last run."""
        stats = SyncStats()
        self._load_state()

        start_token = self._state.get("start_page_token")
        if not start_token:
            raise SyncError("No start_page_token in state — run a full scan first")

        changes, new_token = self._drive.get_changes(start_token)
        logger.info(f"Processing {len(changes)} changes")

        for change in changes:
            try:
                if change.removed:
                    self._handle_delete(change.file_id, stats)
                elif change.file:
                    if change.file.should_skip:
                        continue
                    is_update = change.file_id in self._file_cache
                    self._process_file(change.file, stats, is_update=is_update)
            except Exception as e:
                logger.error(f"Failed to process change for {change.file_id}: {e}")
                stats.failed += 1

        # Commit text file changes
        if stats.added or stats.modified or stats.deleted:
            commit_msg = f"Backup {datetime.now(timezone.utc).isoformat()} — {stats.summary()}"
            self._git.commit(commit_msg)

        # Save state
        if new_token:
            self._state["start_page_token"] = new_token
        self._state["last_run"] = datetime.now(timezone.utc).isoformat()
        self._state["last_run_status"] = "success" if stats.failed == 0 else "partial"
        self._state["file_cache"] = self._file_cache
        self._save_state()

        logger.info(f"Incremental sync complete: {stats.summary()}")
        return stats

    def _check_disk_space(self, required_bytes: int) -> None:
        """Check if sufficient disk space is available."""
        for path in [self._git._path if hasattr(self._git, '_path') else None,
                      self._mirror._path if hasattr(self._mirror, '_path') else None]:
            if path and path.exists():
                usage = shutil.disk_usage(path)
                if usage.free < required_bytes + (100 * 1024 * 1024):  # 100MB buffer
                    raise SyncError(
                        f"Insufficient disk space at {path}: "
                        f"{usage.free // (1024*1024)}MB free, "
                        f"need {required_bytes // (1024*1024)}MB + 100MB buffer"
                    )

    def _process_file(self, drive_file: DriveFile, stats: SyncStats, is_update: bool = False) -> None:
        """Download, classify, and route a single file."""
        # Check file size limit
        if self._max_file_size_bytes and drive_file.size and drive_file.size > self._max_file_size_bytes:
            logger.info(f"Skipping large file: {drive_file.name} ({drive_file.size} bytes)")
            stats.skipped += 1
            return

        # Check disk space before downloading
        if drive_file.size:
            self._check_disk_space(drive_file.size)

        # Check if file has actually changed (MD5)
        if not is_update and drive_file.id in self._file_cache:
            cached = self._file_cache[drive_file.id]
            if cached.get("md5") == drive_file.md5 and drive_file.md5:
                logger.debug(f"Unchanged (MD5 match): {drive_file.name}")
                return

        # Download or export
        file_name = drive_file.name
        if drive_file.is_exportable:
            export_mime = drive_file.export_mime_type
            content = self._drive.export_file(drive_file.id, export_mime)
            file_name = f"{drive_file.name}{drive_file.export_extension}"
        else:
            content = self._drive.download_file(drive_file.id)

        # Classify
        file_type = self._classifier.classify(drive_file.mime_type, content)

        # Resolve local path
        folder_path = self._drive.resolve_file_path(drive_file.parents)
        local_path = self._classifier.resolve_local_path(
            folder_path, sanitize_filename(file_name), drive_file.id, self._file_cache
        )

        # Handle move/rename: if cached path differs from new path, move the file
        old_cached = self._file_cache.get(drive_file.id)
        if old_cached and old_cached.get("local_path") and old_cached["local_path"] != local_path:
            old_path = old_cached["local_path"]
            old_type = old_cached.get("type", "binary")
            if old_type == "text":
                self._git.move_file(old_path, local_path)
            else:
                self._mirror.move_file(old_path, local_path)
            logger.info(f"Moved: {old_path} → {local_path}")

        # Route to git or mirror
        if file_type == FileType.TEXT:
            self._git.write_file(local_path, content)
        else:
            self._mirror.write_file(local_path, content)

        # Update cache
        self._file_cache[drive_file.id] = {
            "type": file_type.value,
            "mime": drive_file.mime_type,
            "local_path": local_path,
            "md5": drive_file.md5,
            "last_modified": drive_file.modified_time,
        }

        if is_update:
            stats.modified += 1
            logger.info(f"Updated: {local_path}")
        else:
            stats.added += 1
            logger.info(f"Added: {local_path} → {'git' if file_type == FileType.TEXT else 'mirror'}")

    def _handle_delete(self, file_id: str, stats: SyncStats) -> None:
        """Handle a deleted file."""
        cached = self._file_cache.get(file_id)
        if not cached:
            return

        local_path = cached["local_path"]
        file_type = cached["type"]

        if file_type == "text":
            self._git.remove_file(local_path)
        else:
            self._mirror.delete_file(local_path)

        del self._file_cache[file_id]
        stats.deleted += 1
        logger.info(f"Deleted: {local_path}")

    def _load_state(self) -> None:
        """Load state from state file."""
        if self._state_file.exists():
            try:
                self._state = json.loads(self._state_file.read_text())
                self._file_cache = self._state.get("file_cache", {})
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"Corrupt state file, starting fresh: {e}")
                self._state = {}
                self._file_cache = {}
        else:
            self._state = {}
            self._file_cache = {}

    def _save_state(self) -> None:
        """Save state to state file."""
        self._state_file.parent.mkdir(parents=True, exist_ok=True)
        self._state_file.write_text(json.dumps(self._state, indent=2))
        logger.debug(f"State saved to {self._state_file}")
