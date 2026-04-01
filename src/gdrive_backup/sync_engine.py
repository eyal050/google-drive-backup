# src/gdrive_backup/sync_engine.py
"""Orchestrates the Google Drive backup process."""

import json
import logging
import os
import shutil
import traceback
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

from gdrive_backup.classifier import FileClassifier, FileType, sanitize_filename
from gdrive_backup.drive_client import DriveClient, DriveFile, GOOGLE_EXPORT_MAP, GOOGLE_EXPORT_EXTENSIONS
from gdrive_backup.git_manager import GitManager, GitError
from gdrive_backup.mirror_manager import MirrorManager, MirrorError

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """Raised when sync fails fatally."""


@dataclass
class FailureRecord:
    """Details about a file that failed to process."""
    file_name: str
    file_id: str
    folder_path: str
    reason: str
    error_message: str


@dataclass
class FolderStats:
    """Per-folder file count and size."""
    file_count: int = 0
    drive_size_bytes: int = 0
    local_size_bytes: int = 0


@dataclass
class FileTypeStats:
    """Per-extension file count and size."""
    count: int = 0
    drive_bytes: int = 0
    local_bytes: int = 0


class DryRunSource(Enum):
    DRIVE_API = "drive_api"
    LOCAL_STATE = "local_state"


@dataclass
class DryRunReport:
    """Report produced by a dry run — no files are written."""
    source: DryRunSource
    text_file_count: int
    binary_file_count: int
    text_size_bytes: int
    binary_size_bytes: int
    sizes_available: bool        # False if state cache lacked size fields
    git_repo_path: str
    mirror_path: str
    auth_method: str
    include_shared: bool
    max_file_size_mb: int
    github_repo: Optional[str]   # from config — not validated against GitHub


@dataclass
class SyncStats:
    """Statistics for a sync run."""
    added: int = 0
    modified: int = 0
    deleted: int = 0
    skipped: int = 0
    failed: int = 0

    # Enriched fields
    total_files: int = 0
    folders: dict = field(default_factory=dict)
    file_types: dict = field(default_factory=dict)
    failures: list = field(default_factory=list)
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    drive_total_bytes: int = 0
    local_total_bytes: int = 0

    def record_file(self, folder_path: str, extension: str, drive_bytes: int, local_bytes: int) -> None:
        """Update per-folder stats, per-file-type stats, and running totals."""
        if folder_path not in self.folders:
            self.folders[folder_path] = FolderStats()
        fs = self.folders[folder_path]
        fs.file_count += 1
        fs.drive_size_bytes += drive_bytes
        fs.local_size_bytes += local_bytes

        if extension not in self.file_types:
            self.file_types[extension] = FileTypeStats()
        ft = self.file_types[extension]
        ft.count += 1
        ft.drive_bytes += drive_bytes
        ft.local_bytes += local_bytes

        self.drive_total_bytes += drive_bytes
        self.local_total_bytes += local_bytes

    def record_failure(self, file_name: str, file_id: str, folder_path: str, reason: str, error_message: str) -> None:
        """Append a FailureRecord to the failures list."""
        self.failures.append(FailureRecord(
            file_name=file_name,
            file_id=file_id,
            folder_path=folder_path,
            reason=reason,
            error_message=error_message,
        ))

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

        logger.debug(
            f"SyncEngine initialized: state_file={state_file}, "
            f"max_file_size_mb={max_file_size_mb}, include_shared={include_shared}, "
            f"folder_ids={self._folder_ids}"
        )

    @property
    def git_manager(self) -> GitManager:
        """Expose the underlying GitManager for post-run operations (e.g. push)."""
        return self._git

    def run(self) -> SyncStats:
        """Run a backup — auto-selects full scan or incremental."""
        logger.info("Starting backup run")
        try:
            self._load_state()
        except Exception as e:
            logger.error(f"Failed to load state: {e}")
            raise SyncError(f"Failed to load state: {e}") from e

        if self._state.get("start_page_token"):
            logger.info("Running incremental backup (found start_page_token in state)")
            return self.run_incremental()
        else:
            logger.info("Running full scan (first run — no start_page_token)")
            return self.run_full_scan()

    def run_full_scan(self) -> SyncStats:
        """Enumerate all Drive files and download them."""
        stats = SyncStats()
        self._load_state()

        logger.info("Starting full scan...")

        # Get start token for future incremental runs
        try:
            start_token = self._drive.get_start_page_token()
            logger.debug(f"Got start_page_token: {start_token}")
        except Exception as e:
            logger.error(f"Failed to get start page token: {e}")
            raise SyncError(f"Failed to get start page token from Drive API: {e}") from e

        file_count = 0
        try:
            for drive_file in self._drive.list_all_files(
                include_shared=self._include_shared,
                folder_ids=self._folder_ids if self._folder_ids else None,
            ):
                file_count += 1
                if drive_file.should_skip:
                    logger.debug(f"Skipping non-downloadable: {drive_file.name} ({drive_file.mime_type})")
                    continue

                try:
                    self._process_file(drive_file, stats)
                except Exception as e:
                    reason = self._categorize_failure(e)
                    folder_path = ""
                    try:
                        folder_path = self._drive.resolve_file_path(drive_file.parents)
                    except Exception:
                        pass
                    stats.record_failure(
                        file_name=drive_file.name,
                        file_id=drive_file.id,
                        folder_path=folder_path,
                        reason=reason,
                        error_message=str(e),
                    )
                    logger.error(
                        f"Failed to process file '{drive_file.name}' (id={drive_file.id}): {e}",
                        exc_info=True,
                    )
                    stats.failed += 1
        except Exception as e:
            logger.error(f"Error listing files from Drive API after {file_count} files: {e}", exc_info=True)
            if file_count == 0:
                raise SyncError(f"Failed to list any files from Drive API: {e}") from e
            logger.warning(f"Continuing with {file_count} files processed before error")

        # Commit all text file changes
        try:
            commit_msg = f"Backup {datetime.now(timezone.utc).isoformat()} — {stats.summary()}"
            sha = self._git.commit(commit_msg)
            if sha:
                logger.info(f"Created commit {sha[:8]}: {commit_msg}")
            else:
                logger.debug("No text file changes to commit")
        except GitError as e:
            logger.error(f"Failed to create git commit: {e}", exc_info=True)
            stats.failed += 1

        # Save state
        self._state["start_page_token"] = start_token
        self._state["last_run"] = datetime.now(timezone.utc).isoformat()
        self._state["last_run_status"] = "success" if stats.failed == 0 else "partial"
        self._state["file_cache"] = self._file_cache
        try:
            self._save_state()
        except Exception as e:
            logger.error(f"Failed to save state: {e}", exc_info=True)

        stats.end_time = datetime.now(timezone.utc)
        logger.info(f"Full scan complete: {stats.summary()}")
        return stats

    def run_incremental(self) -> SyncStats:
        """Process only changes since last run."""
        stats = SyncStats()
        self._load_state()

        start_token = self._state.get("start_page_token")
        if not start_token:
            raise SyncError("No start_page_token in state — run a full scan first")

        logger.debug(f"Fetching changes since token: {start_token}")
        try:
            changes, new_token = self._drive.get_changes(start_token)
        except Exception as e:
            logger.error(f"Failed to fetch changes from Drive API: {e}", exc_info=True)
            raise SyncError(f"Failed to fetch changes: {e}") from e

        logger.info(f"Processing {len(changes)} changes")

        for i, change in enumerate(changes):
            try:
                logger.debug(
                    f"Change {i+1}/{len(changes)}: file_id={change.file_id}, "
                    f"removed={change.removed}, has_file={change.file is not None}"
                )
                if change.removed:
                    self._handle_delete(change.file_id, stats)
                elif change.file:
                    if change.file.should_skip:
                        logger.debug(f"Skipping non-downloadable change: {change.file.name}")
                        continue
                    is_update = change.file_id in self._file_cache
                    self._process_file(change.file, stats, is_update=is_update)
            except Exception as e:
                reason = self._categorize_failure(e)
                file_name = change.file.name if change.file else f"file_id={change.file_id}"
                folder_path = ""
                if change.file:
                    try:
                        folder_path = self._drive.resolve_file_path(change.file.parents)
                    except Exception:
                        pass
                stats.record_failure(
                    file_name=file_name,
                    file_id=change.file_id,
                    folder_path=folder_path,
                    reason=reason,
                    error_message=str(e),
                )
                logger.error(
                    f"Failed to process change for file_id={change.file_id}: {e}",
                    exc_info=True,
                )
                stats.failed += 1

        # Commit text file changes
        if stats.added or stats.modified or stats.deleted:
            try:
                commit_msg = f"Backup {datetime.now(timezone.utc).isoformat()} — {stats.summary()}"
                sha = self._git.commit(commit_msg)
                if sha:
                    logger.info(f"Created commit {sha[:8]}: {commit_msg}")
            except GitError as e:
                logger.error(f"Failed to create git commit: {e}", exc_info=True)
                stats.failed += 1

        # Save state
        if new_token:
            self._state["start_page_token"] = new_token
            logger.debug(f"Updated start_page_token: {new_token}")
        self._state["last_run"] = datetime.now(timezone.utc).isoformat()
        self._state["last_run_status"] = "success" if stats.failed == 0 else "partial"
        self._state["file_cache"] = self._file_cache
        try:
            self._save_state()
        except Exception as e:
            logger.error(f"Failed to save state: {e}", exc_info=True)

        stats.end_time = datetime.now(timezone.utc)
        logger.info(f"Incremental sync complete: {stats.summary()}")
        return stats

    def run_dry(
        self,
        git_repo_path: str,
        mirror_path: str,
        auth_method: str,
        max_file_size_mb: int,
        github_repo: Optional[str] = None,
    ) -> DryRunReport:
        """Enumerate Drive files and return counts/sizes without writing anything.

        Falls back to local state cache if Drive API is unavailable.
        Raises SyncError if both are unavailable.
        """
        self._load_state()

        text_count = binary_count = 0
        text_bytes = binary_bytes = 0
        source = DryRunSource.DRIVE_API
        sizes_available = True

        try:
            file_count = 0
            for drive_file in self._drive.list_all_files(
                include_shared=self._include_shared,
                folder_ids=self._folder_ids if self._folder_ids else None,
            ):
                if drive_file.should_skip:
                    continue
                file_count += 1
                file_type = self._classifier.classify_by_mime(drive_file.mime_type)
                size = drive_file.size or 0
                if file_type == FileType.TEXT:
                    text_count += 1
                    text_bytes += size
                else:
                    binary_count += 1
                    binary_bytes += size
            logger.info(f"Dry run enumerated {file_count} files from Drive API")
        except Exception as e:
            logger.warning(f"Drive API unavailable for dry run, falling back to state: {e}")
            source = DryRunSource.LOCAL_STATE
            if not self._file_cache:
                raise SyncError(
                    "Cannot enumerate files: Drive API failed and no local state exists"
                ) from e
            for entry in self._file_cache.values():
                raw_size = entry.get("size")
                if raw_size is None:
                    sizes_available = False
                    raw_size = 0
                if entry.get("type") == "text":
                    text_count += 1
                    text_bytes += raw_size
                else:
                    binary_count += 1
                    binary_bytes += raw_size

        return DryRunReport(
            source=source,
            text_file_count=text_count,
            binary_file_count=binary_count,
            text_size_bytes=text_bytes,
            binary_size_bytes=binary_bytes,
            sizes_available=sizes_available,
            git_repo_path=git_repo_path,
            mirror_path=mirror_path,
            auth_method=auth_method,
            include_shared=self._include_shared,
            max_file_size_mb=max_file_size_mb,
            github_repo=github_repo,
        )

    def _check_disk_space(self, required_bytes: int) -> None:
        """Check if sufficient disk space is available."""
        for path in [self._git._path if hasattr(self._git, '_path') else None,
                      self._mirror._path if hasattr(self._mirror, '_path') else None]:
            if path and path.exists():
                try:
                    usage = shutil.disk_usage(path)
                    if usage.free < required_bytes + (100 * 1024 * 1024):  # 100MB buffer
                        raise SyncError(
                            f"Insufficient disk space at {path}: "
                            f"{usage.free // (1024*1024)}MB free, "
                            f"need {required_bytes // (1024*1024)}MB + 100MB buffer"
                        )
                except SyncError:
                    raise
                except Exception as e:
                    logger.warning(f"Could not check disk space at {path}: {e}")

    @staticmethod
    def _categorize_failure(error: Exception) -> str:
        """Classify an exception into a failure reason category."""
        from googleapiclient.errors import HttpError as _HttpError
        if isinstance(error, SyncError):
            msg = str(error).lower()
            if "disk space" in msg or "insufficient" in msg:
                return "disk_full"
            if "file size" in msg or "exceeds limit" in msg:
                return "too_large"
        if isinstance(error, _HttpError):
            if error.resp.status == 403:
                return "permission_denied"
            if error.resp.status >= 500:
                return "download_error"
        msg = str(error).lower()
        if "export" in msg:
            return "export_failed"
        if "permission" in msg or "403" in msg:
            return "permission_denied"
        return "unknown"

    def _process_file(self, drive_file: DriveFile, stats: SyncStats, is_update: bool = False) -> None:
        """Download, classify, and route a single file."""
        logger.debug(
            f"Processing file: name='{drive_file.name}', id={drive_file.id}, "
            f"mime={drive_file.mime_type}, size={drive_file.size}, is_update={is_update}"
        )

        # Check file size limit
        if self._max_file_size_bytes and drive_file.size and drive_file.size > self._max_file_size_bytes:
            logger.info(
                f"Skipping large file: {drive_file.name} "
                f"({drive_file.size} bytes > limit {self._max_file_size_bytes} bytes)"
            )
            stats.skipped += 1
            return

        # Check disk space before downloading
        if drive_file.size:
            try:
                self._check_disk_space(drive_file.size)
            except SyncError as e:
                logger.error(f"Disk space check failed for {drive_file.name}: {e}")
                raise

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
            logger.debug(f"Exporting Google-native file: {drive_file.name} as {export_mime}")
            try:
                content = self._drive.export_file(drive_file.id, export_mime)
            except Exception as e:
                logger.error(f"Failed to export file '{drive_file.name}' (id={drive_file.id}): {e}")
                raise
            file_name = f"{drive_file.name}{drive_file.export_extension}"
        else:
            logger.debug(f"Downloading file: {drive_file.name}")
            try:
                content = self._drive.download_file(drive_file.id)
            except Exception as e:
                logger.error(f"Failed to download file '{drive_file.name}' (id={drive_file.id}): {e}")
                raise

        logger.debug(f"Downloaded {len(content)} bytes for '{drive_file.name}'")

        # Classify
        file_type = self._classifier.classify(drive_file.mime_type, content)
        logger.debug(f"Classified '{drive_file.name}' as {file_type.value}")

        # Resolve local path
        try:
            folder_path = self._drive.resolve_file_path(drive_file.parents)
        except Exception as e:
            logger.warning(f"Failed to resolve path for '{drive_file.name}', using root: {e}")
            folder_path = ""

        local_path = self._classifier.resolve_local_path(
            folder_path, sanitize_filename(file_name), drive_file.id, self._file_cache
        )
        logger.debug(f"Resolved local path: {local_path}")

        # Handle move/rename: if cached path differs from new path, move the file
        old_cached = self._file_cache.get(drive_file.id)
        if old_cached and old_cached.get("local_path") and old_cached["local_path"] != local_path:
            old_path = old_cached["local_path"]
            old_type = old_cached.get("type", "binary")
            try:
                if old_type == "text":
                    self._git.move_file(old_path, local_path)
                else:
                    self._mirror.move_file(old_path, local_path)
                logger.info(f"Moved: {old_path} -> {local_path}")
            except Exception as e:
                logger.warning(f"Failed to move '{old_path}' -> '{local_path}': {e}. Will write to new path.")

        # Route to git or mirror
        try:
            if file_type == FileType.TEXT:
                self._git.write_file(local_path, content)
            else:
                self._mirror.write_file(local_path, content)
        except (GitError, MirrorError) as e:
            logger.error(f"Failed to write file '{local_path}': {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error writing file '{local_path}': {e}", exc_info=True)
            raise

        # Update cache
        self._file_cache[drive_file.id] = {
            "type": file_type.value,
            "mime": drive_file.mime_type,
            "local_path": local_path,
            "md5": drive_file.md5,
            "last_modified": drive_file.modified_time,
            "size": drive_file.size,
        }

        # Collect enriched stats
        ext = Path(local_path).suffix
        drive_bytes = drive_file.size or 0
        local_bytes = len(content)
        stats.record_file(folder_path, ext, drive_bytes, local_bytes)

        if is_update:
            stats.modified += 1
            logger.info(f"Updated: {local_path}")
        else:
            stats.added += 1
            logger.info(f"Added: {local_path} -> {'git' if file_type == FileType.TEXT else 'mirror'}")

    def _handle_delete(self, file_id: str, stats: SyncStats) -> None:
        """Handle a deleted file."""
        cached = self._file_cache.get(file_id)
        if not cached:
            logger.debug(f"Delete for unknown file_id={file_id} (not in cache), skipping")
            return

        local_path = cached["local_path"]
        file_type = cached["type"]
        logger.debug(f"Deleting {file_type} file: {local_path} (file_id={file_id})")

        try:
            if file_type == "text":
                self._git.remove_file(local_path)
            else:
                self._mirror.delete_file(local_path)
        except Exception as e:
            logger.error(f"Failed to delete file '{local_path}': {e}", exc_info=True)
            stats.failed += 1
            return

        del self._file_cache[file_id]
        stats.deleted += 1
        logger.info(f"Deleted: {local_path}")

    def _load_state(self) -> None:
        """Load state from state file."""
        if self._state_file.exists():
            logger.debug(f"Loading state from {self._state_file}")
            try:
                raw = self._state_file.read_text()
                self._state = json.loads(raw)
                self._file_cache = self._state.get("file_cache", {})
                logger.info(
                    f"State loaded: {len(self._file_cache)} files in cache, "
                    f"last_run={self._state.get('last_run', 'never')}, "
                    f"status={self._state.get('last_run_status', 'unknown')}"
                )
            except json.JSONDecodeError as e:
                logger.warning(f"Corrupt state file (invalid JSON), starting fresh: {e}")
                self._state = {}
                self._file_cache = {}
            except Exception as e:
                logger.warning(f"Failed to load state file, starting fresh: {e}")
                self._state = {}
                self._file_cache = {}
        else:
            logger.debug(f"No state file at {self._state_file}, starting fresh")
            self._state = {}
            self._file_cache = {}

    def _save_state(self) -> None:
        """Save state to state file."""
        logger.debug(f"Saving state to {self._state_file} ({len(self._file_cache)} files in cache)")
        try:
            self._state_file.parent.mkdir(parents=True, exist_ok=True)
            self._state_file.write_text(json.dumps(self._state, indent=2))
            logger.debug(f"State saved to {self._state_file}")
        except Exception as e:
            logger.error(f"Failed to save state to {self._state_file}: {e}", exc_info=True)
            raise
