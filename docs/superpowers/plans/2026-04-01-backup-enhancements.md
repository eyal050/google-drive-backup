# Backup Enhancements v0.2.0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add rich backup summaries, JSON log, unified setup, live progress, and version bump to gdrive-backup.

**Architecture:** Enrich the existing `SyncStats` dataclass to carry per-folder stats, failure details, file type breakdown, and timing. The sync engine populates stats during processing; the CLI reads them for terminal display and JSON log writing. A `ProgressTracker` class in `sync_engine.py` handles live progress output. The `init` command absorbs `scripts/setup.py` logic for a single setup flow.

**Tech Stack:** Python 3.10+, Click, GitPython, Google Drive API, PyYAML, requests

---

### Task 1: Version Bump

**Files:**
- Modify: `pyproject.toml:6`
- Modify: `src/gdrive_backup/__init__.py:3`

- [ ] **Step 1: Bump version in pyproject.toml**

```python
# pyproject.toml line 6
version = "0.2.0"
```

- [ ] **Step 2: Bump version in __init__.py**

```python
# src/gdrive_backup/__init__.py line 3
__version__ = "0.2.0"
```

- [ ] **Step 3: Commit**

```bash
git add pyproject.toml src/gdrive_backup/__init__.py
git commit -m "chore: bump version to 0.2.0"
```

---

### Task 2: Enrich SyncStats with New Data Structures

**Files:**
- Modify: `src/gdrive_backup/sync_engine.py:1-71`
- Test: `tests/test_sync_engine.py`

- [ ] **Step 1: Write tests for new data structures**

Add to `tests/test_sync_engine.py`:

```python
from gdrive_backup.sync_engine import (
    SyncEngine, SyncStats, SyncError,
    DryRunSource, DryRunReport,
    FailureRecord, FolderStats, FileTypeStats,
)


class TestSyncStatsEnriched:
    def test_default_new_fields(self):
        stats = SyncStats()
        assert stats.total_files == 0
        assert stats.folders == {}
        assert stats.file_types == {}
        assert stats.failures == []
        assert stats.drive_total_bytes == 0
        assert stats.local_total_bytes == 0
        assert stats.start_time is not None
        assert stats.end_time is None

    def test_record_file_updates_folder_stats(self):
        stats = SyncStats()
        stats.record_file("My Drive/Photos", ".jpg", drive_bytes=5000, local_bytes=4800)
        stats.record_file("My Drive/Photos", ".png", drive_bytes=3000, local_bytes=2900)
        stats.record_file("My Drive/Docs", ".docx", drive_bytes=1000, local_bytes=950)

        assert stats.folders["My Drive/Photos"].file_count == 2
        assert stats.folders["My Drive/Photos"].drive_size_bytes == 8000
        assert stats.folders["My Drive/Photos"].local_size_bytes == 7700
        assert stats.folders["My Drive/Docs"].file_count == 1
        assert stats.file_types[".jpg"].count == 1
        assert stats.file_types[".jpg"].drive_bytes == 5000
        assert stats.file_types[".png"].count == 1
        assert stats.drive_total_bytes == 9000
        assert stats.local_total_bytes == 8650

    def test_record_failure(self):
        stats = SyncStats()
        stats.record_failure("big.mp4", "file123", "My Drive/Videos", "too_large", "2.1 GB exceeds limit")
        assert len(stats.failures) == 1
        assert stats.failures[0].reason == "too_large"
        assert stats.failures[0].file_name == "big.mp4"

    def test_summary_still_works(self):
        stats = SyncStats(added=3, failed=1)
        assert "3 added" in stats.summary()
        assert "1 failed" in stats.summary()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_sync_engine.py::TestSyncStatsEnriched -v`
Expected: FAIL — `FailureRecord`, `FolderStats`, `FileTypeStats` not importable, `record_file` / `record_failure` not defined.

- [ ] **Step 3: Implement new data structures and methods**

In `src/gdrive_backup/sync_engine.py`, add these dataclasses after `SyncError` (before `DryRunSource`), and update `SyncStats`:

```python
@dataclass
class FailureRecord:
    """Details about a file that failed to process."""
    file_name: str
    file_id: str
    folder_path: str
    reason: str          # "too_large", "export_failed", "permission_denied", "disk_full", "download_error", "unknown"
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
```

Update `SyncStats` to:

```python
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
    folders: dict = field(default_factory=dict)        # str -> FolderStats
    file_types: dict = field(default_factory=dict)      # str -> FileTypeStats
    failures: list = field(default_factory=list)        # List[FailureRecord]
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: Optional[datetime] = None
    drive_total_bytes: int = 0
    local_total_bytes: int = 0

    def record_file(self, folder_path: str, extension: str, drive_bytes: int, local_bytes: int) -> None:
        """Record a successfully processed file's stats."""
        # Folder stats
        if folder_path not in self.folders:
            self.folders[folder_path] = FolderStats()
        fs = self.folders[folder_path]
        fs.file_count += 1
        fs.drive_size_bytes += drive_bytes
        fs.local_size_bytes += local_bytes

        # File type stats
        ext = extension.lower() if extension else "(no extension)"
        if ext not in self.file_types:
            self.file_types[ext] = FileTypeStats()
        ft = self.file_types[ext]
        ft.count += 1
        ft.drive_bytes += drive_bytes
        ft.local_bytes += local_bytes

        # Totals
        self.drive_total_bytes += drive_bytes
        self.local_total_bytes += local_bytes

    def record_failure(self, file_name: str, file_id: str, folder_path: str, reason: str, error_message: str) -> None:
        """Record a file processing failure with details."""
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
```

Note: the import for `field` from `dataclasses` is already present at line 9.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_sync_engine.py::TestSyncStatsEnriched -v`
Expected: All 4 tests PASS.

- [ ] **Step 5: Run full test suite to verify no regressions**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_sync_engine.py -v`
Expected: All existing tests still PASS.

- [ ] **Step 6: Commit**

```bash
git add src/gdrive_backup/sync_engine.py tests/test_sync_engine.py
git commit -m "feat: enrich SyncStats with folder stats, file types, and failure tracking"
```

---

### Task 3: Wire Stats Collection into Sync Engine Processing

**Files:**
- Modify: `src/gdrive_backup/sync_engine.py:345-456` (`_process_file` method)
- Modify: `src/gdrive_backup/sync_engine.py:125-188` (`run_full_scan` method)
- Test: `tests/test_sync_engine.py`

- [ ] **Step 1: Write tests for stats collection during processing**

Add to `tests/test_sync_engine.py`:

```python
class TestStatsCollection:
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

    def test_full_scan_collects_folder_and_type_stats(self, engine, mock_drive, mock_git):
        f1 = _make_drive_file(id="f1", name="photo.jpg", mime="image/jpeg", size=5000, parents=["p1"])
        f2 = _make_drive_file(id="f2", name="doc.txt", mime="text/plain", size=1000, parents=["p2"])
        mock_drive.list_all_files.return_value = iter([f1, f2])
        mock_drive.get_start_page_token.return_value = "token1"
        mock_drive.download_file.side_effect = [b"x" * 4800, b"y" * 950]
        mock_drive.resolve_file_path.side_effect = ["Photos", "Docs"]

        stats = engine.run_full_scan()

        assert "Photos" in stats.folders
        assert stats.folders["Photos"].file_count == 1
        assert stats.folders["Photos"].drive_size_bytes == 5000
        assert stats.file_types[".jpg"].count == 1
        assert stats.file_types[".txt"].count == 1
        assert stats.drive_total_bytes == 6000
        assert stats.local_total_bytes == 4800 + 950

    def test_full_scan_records_failures_with_reason(self, engine, mock_drive):
        f1 = _make_drive_file(id="f1", name="big.mp4", size=200)
        engine._max_file_size_bytes = 100
        f2 = _make_drive_file(id="f2", name="secret.pdf", size=50)
        mock_drive.list_all_files.return_value = iter([f1, f2])
        mock_drive.get_start_page_token.return_value = "token1"
        mock_drive.download_file.side_effect = HttpError(
            resp=MagicMock(status=403), content=b"forbidden"
        )
        mock_drive.resolve_file_path.return_value = "Folder"

        stats = engine.run_full_scan()

        # f1 skipped (too large) — this is a skip not a failure
        assert stats.skipped == 1
        # f2 fails with permission denied
        assert stats.failed == 1
        assert len(stats.failures) == 1
        assert stats.failures[0].reason == "permission_denied"

    def test_full_scan_sets_end_time(self, engine, mock_drive):
        mock_drive.list_all_files.return_value = iter([])
        mock_drive.get_start_page_token.return_value = "token1"

        stats = engine.run_full_scan()

        assert stats.end_time is not None
        assert stats.end_time >= stats.start_time
```

Also add this import at the top of the test file:

```python
from googleapiclient.errors import HttpError
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_sync_engine.py::TestStatsCollection -v`
Expected: FAIL — stats fields not populated during processing.

- [ ] **Step 3: Update _process_file to collect stats**

In `src/gdrive_backup/sync_engine.py`, modify the `_process_file` method. After the file is successfully written and cached (around line 441-455), add stats collection:

Replace the existing cache update + stats increment block at lines 441-455:

```python
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
```

- [ ] **Step 4: Add failure categorization in run_full_scan**

In `run_full_scan`, replace the generic failure handling in the file processing loop (lines 151-158):

```python
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
```

- [ ] **Step 5: Add failure categorization in run_incremental**

Similarly update the failure handling in `run_incremental` (lines 222-227):

```python
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
```

- [ ] **Step 6: Add the _categorize_failure helper and set end_time**

Add this method to `SyncEngine`:

```python
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
```

Also add `stats.end_time = datetime.now(timezone.utc)` at the end of `run_full_scan` (right before `return stats`) and `run_incremental` (right before `return stats`).

- [ ] **Step 7: Run tests to verify they pass**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_sync_engine.py -v`
Expected: All tests PASS (both new and existing).

- [ ] **Step 8: Commit**

```bash
git add src/gdrive_backup/sync_engine.py tests/test_sync_engine.py
git commit -m "feat: collect per-folder stats, file types, and categorized failures during sync"
```

---

### Task 4: Add count_files to DriveClient

**Files:**
- Modify: `src/gdrive_backup/drive_client.py`
- Test: `tests/test_drive_client.py`

- [ ] **Step 1: Write test for count_files**

Add to `tests/test_drive_client.py`:

```python
class TestCountFiles:
    def test_count_files_returns_total(self):
        service = MagicMock()
        client = DriveClient(service)

        # Two pages of results: 3 files on page 1, 2 on page 2
        page1 = {"files": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "nextPageToken": "tok2"}
        page2 = {"files": [{"id": "4"}, {"id": "5"}]}
        service.files.return_value.list.return_value.execute.side_effect = [page1, page2]

        count = client.count_files()

        assert count == 5

    def test_count_files_with_folder_filter(self):
        service = MagicMock()
        client = DriveClient(service)

        page1 = {"files": [{"id": "1"}]}
        service.files.return_value.list.return_value.execute.return_value = page1

        count = client.count_files(folder_ids=["folder1"])

        assert count == 1
        # Verify query includes folder filter
        call_kwargs = service.files.return_value.list.call_args
        assert "folder1" in call_kwargs.kwargs.get("q", call_kwargs[1].get("q", ""))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_drive_client.py::TestCountFiles -v`
Expected: FAIL — `count_files` not defined.

- [ ] **Step 3: Implement count_files**

Add to `DriveClient` in `src/gdrive_backup/drive_client.py`:

```python
    def count_files(
        self,
        include_shared: bool = False,
        folder_ids: Optional[List[str]] = None,
    ) -> int:
        """Count total files in Drive without downloading metadata.

        Uses the same query as list_all_files but requests only file IDs
        for efficiency. Pages through all results to get exact total.
        """
        query_parts = ["trashed = false"]
        if not include_shared:
            query_parts.append("'me' in owners")
        if folder_ids:
            folder_q = " or ".join(f"'{fid}' in parents" for fid in folder_ids)
            query_parts.append(f"({folder_q})")

        query = " and ".join(query_parts)
        logger.info(f"Counting files with query: {query}")
        page_token = None
        total = 0

        while True:
            self._limiter.wait()
            try:
                response = self._execute_with_retry(
                    self._service.files().list(
                        q=query,
                        fields="nextPageToken, files(id)",
                        pageSize=1000,
                        pageToken=page_token,
                    )
                )
            except Exception as e:
                logger.error(f"Failed to count files ({total} counted so far): {e}")
                raise

            total += len(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"Total files counted: {total}")
        return total
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_drive_client.py::TestCountFiles -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/drive_client.py tests/test_drive_client.py
git commit -m "feat: add count_files method to DriveClient for upfront file counting"
```

---

### Task 5: Live Progress Tracker

**Files:**
- Modify: `src/gdrive_backup/sync_engine.py`
- Test: `tests/test_sync_engine.py`

- [ ] **Step 1: Write tests for ProgressTracker**

Add to `tests/test_sync_engine.py`:

```python
import io
from gdrive_backup.sync_engine import ProgressTracker


class TestProgressTracker:
    def test_update_increments_count(self):
        output = io.StringIO()
        tracker = ProgressTracker(total=100, output=output, is_tty=False)
        tracker.update("file1.txt")
        tracker.update("file2.txt")
        assert tracker.processed == 2

    def test_non_tty_prints_periodic_updates(self):
        output = io.StringIO()
        tracker = ProgressTracker(total=200, output=output, is_tty=False)
        for i in range(101):
            tracker.update(f"file{i}.txt")
        text = output.getvalue()
        # Non-TTY should print at 100-file intervals
        assert "100/200" in text

    def test_tty_uses_carriage_return(self):
        output = io.StringIO()
        tracker = ProgressTracker(total=10, output=output, is_tty=True)
        tracker.update("test.txt")
        text = output.getvalue()
        assert "\r" in text

    def test_finish_prints_newline(self):
        output = io.StringIO()
        tracker = ProgressTracker(total=1, output=output, is_tty=True)
        tracker.update("file.txt")
        tracker.finish()
        text = output.getvalue()
        assert text.endswith("\n")

    def test_zero_total_no_crash(self):
        output = io.StringIO()
        tracker = ProgressTracker(total=0, output=output, is_tty=True)
        tracker.finish()  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_sync_engine.py::TestProgressTracker -v`
Expected: FAIL — `ProgressTracker` not importable.

- [ ] **Step 3: Implement ProgressTracker**

Add to `src/gdrive_backup/sync_engine.py` after the `SyncStats` class:

```python
class ProgressTracker:
    """Displays live progress during backup processing."""

    def __init__(self, total: int, output=None, is_tty: bool = True):
        self.total = total
        self.processed = 0
        self._output = output or sys.stderr
        self._is_tty = is_tty
        self._start_time = time.monotonic()
        self._bar_width = 30

    def update(self, file_name: str) -> None:
        """Record one processed file and update the display."""
        self.processed += 1
        if self._is_tty:
            self._print_tty(file_name)
        elif self.processed % 100 == 0 or self.processed == self.total:
            self._print_log()

    def finish(self) -> None:
        """Print a final newline to clear the progress line."""
        if self._is_tty and self.total > 0:
            self._output.write("\n")
            try:
                self._output.flush()
            except Exception:
                pass

    def _print_tty(self, file_name: str) -> None:
        if self.total == 0:
            return
        pct = self.processed / self.total
        filled = int(self._bar_width * pct)
        bar = "#" * filled + "-" * (self._bar_width - filled)
        eta = self._format_eta()
        # Truncate long file names
        max_name = 30
        display_name = file_name[:max_name] + "..." if len(file_name) > max_name else file_name
        line = f"\r[{self.processed:>{len(str(self.total))}}/{self.total}] {pct:>4.0%} |{bar}| {eta} - {display_name}"
        # Pad to overwrite previous line
        self._output.write(line.ljust(120) + "\r")
        try:
            self._output.flush()
        except Exception:
            pass

    def _print_log(self) -> None:
        eta = self._format_eta()
        self._output.write(f"Processed {self.processed}/{self.total} files... {eta}\n")
        try:
            self._output.flush()
        except Exception:
            pass

    def _format_eta(self) -> str:
        elapsed = time.monotonic() - self._start_time
        if self.processed == 0 or elapsed < 1:
            return "estimating..."
        rate = self.processed / elapsed
        remaining = (self.total - self.processed) / rate
        if remaining < 60:
            return f"{remaining:.0f}s remaining"
        elif remaining < 3600:
            return f"{remaining / 60:.0f}m {remaining % 60:.0f}s remaining"
        else:
            return f"{remaining / 3600:.0f}h {(remaining % 3600) / 60:.0f}m remaining"
```

Also add these imports at the top of `sync_engine.py`:

```python
import sys
import time
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_sync_engine.py::TestProgressTracker -v`
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/sync_engine.py tests/test_sync_engine.py
git commit -m "feat: add ProgressTracker for live backup progress display"
```

---

### Task 6: Integrate Progress Tracker + Count into Sync Engine

**Files:**
- Modify: `src/gdrive_backup/sync_engine.py` (SyncEngine class)

- [ ] **Step 1: Add progress_callback to SyncEngine.__init__**

Update `SyncEngine.__init__` to accept an optional progress callback and quiet flag:

```python
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
        quiet: bool = False,
    ):
        # ... existing assignments ...
        self._quiet = quiet
```

- [ ] **Step 2: Update run_full_scan to use count + progress**

In `run_full_scan`, after getting the start token and before the file loop, add the count pass and progress tracker:

```python
        # Count files for progress tracking
        total_files = 0
        if not self._quiet:
            try:
                total_files = self._drive.count_files(
                    include_shared=self._include_shared,
                    folder_ids=self._folder_ids if self._folder_ids else None,
                )
                stats.total_files = total_files
                logger.info(f"Total files to process: {total_files}")
            except Exception as e:
                logger.warning(f"Could not count files for progress display: {e}")

        tracker = ProgressTracker(
            total=total_files,
            is_tty=sys.stderr.isatty() and not self._quiet,
        ) if not self._quiet else None
```

Then, inside the file loop, after `_process_file` (or after the skip), update the tracker:

```python
                if tracker:
                    tracker.update(drive_file.name)
```

And after the file loop completes:

```python
        if tracker:
            tracker.finish()
```

- [ ] **Step 3: Run full test suite to verify no regressions**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/ -v`
Expected: All tests PASS. (Existing tests don't pass `quiet` — defaults to `False`, tracker created but output goes to real stderr which is fine in tests.)

- [ ] **Step 4: Commit**

```bash
git add src/gdrive_backup/sync_engine.py
git commit -m "feat: integrate file count pass and progress tracker into sync engine"
```

---

### Task 7: Rich Completion Summary in CLI

**Files:**
- Modify: `src/gdrive_backup/cli.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write test for completion summary**

Add to `tests/test_cli.py`:

```python
from gdrive_backup.sync_engine import SyncStats, FolderStats, FileTypeStats, FailureRecord
from datetime import datetime, timezone, timedelta


def test_run_prints_rich_summary(tmp_path, fake_config_file):
    """After backup, CLI prints detailed summary with types and folders."""
    runner = CliRunner()
    stats = SyncStats(added=100, failed=2)
    stats.total_files = 110
    stats.drive_total_bytes = 1_000_000_000
    stats.local_total_bytes = 950_000_000
    stats.end_time = stats.start_time + timedelta(minutes=4, seconds=32)
    stats.folders["My Drive/Photos"] = FolderStats(file_count=80, drive_size_bytes=800_000_000, local_size_bytes=760_000_000)
    stats.folders["My Drive/Docs"] = FolderStats(file_count=20, drive_size_bytes=200_000_000, local_size_bytes=190_000_000)
    stats.file_types[".jpg"] = FileTypeStats(count=70, drive_bytes=700_000_000, local_bytes=660_000_000)
    stats.file_types[".pdf"] = FileTypeStats(count=30, drive_bytes=300_000_000, local_bytes=290_000_000)
    stats.record_failure("big.mp4", "f1", "Videos", "too_large", "exceeds limit")
    stats.record_failure("secret.docx", "f2", "Work", "permission_denied", "403")

    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine, \
         patch("gdrive_backup.cli.setup_logging"):
        mock_cfg.return_value = MagicMock(
            github=None, log_dir=tmp_path, log_max_size_mb=10,
            log_max_files=5, log_default_level="info",
        )
        engine = MagicMock()
        engine.run.return_value = stats
        mock_engine.return_value = engine
        result = runner.invoke(main, ["run", "--config", str(fake_config_file)])

    assert "4m 32s" in result.output
    assert ".jpg" in result.output
    assert ".pdf" in result.output
    assert "My Drive/Photos" in result.output
    assert "too_large" in result.output or "Too large" in result.output
    assert "permission_denied" in result.output or "Permission denied" in result.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_cli.py::test_run_prints_rich_summary -v`
Expected: FAIL — output doesn't contain rich summary yet.

- [ ] **Step 3: Implement _print_completion_summary**

Add to `src/gdrive_backup/cli.py`:

```python
def _format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours = minutes // 60
    mins = minutes % 60
    return f"{hours}h {mins}m"


def _print_completion_summary(stats) -> None:
    """Print a rich backup completion summary."""
    # Duration
    duration = ""
    if stats.end_time and stats.start_time:
        elapsed = (stats.end_time - stats.start_time).total_seconds()
        duration = f" in {_format_duration(elapsed)}"

    click.echo(f"\nBackup complete{duration}\n")

    # File counts
    click.echo(f"  Files: {stats.summary()}")

    # Storage
    if stats.drive_total_bytes > 0 or stats.local_total_bytes > 0:
        click.echo(f"  Storage: {_format_bytes(stats.drive_total_bytes)} on Drive -> {_format_bytes(stats.local_total_bytes)} local")

    # By type (sorted by count descending)
    if stats.file_types:
        click.echo("\n  By type:")
        sorted_types = sorted(stats.file_types.items(), key=lambda x: x[1].count, reverse=True)
        for ext, ft in sorted_types:
            click.echo(f"    {ext:<25} {ft.count:>6,} files  {_format_bytes(ft.local_bytes):>10}")

    # Top 10 folders (sorted by file count descending)
    if stats.folders:
        sorted_folders = sorted(stats.folders.items(), key=lambda x: x[1].file_count, reverse=True)
        top = sorted_folders[:10]
        click.echo(f"\n  Top folders ({min(10, len(sorted_folders))}):")
        for path, fs in top:
            display_path = path if path else "(root)"
            click.echo(f"    {display_path:<40} {fs.file_count:>6,} files  {_format_bytes(fs.local_size_bytes):>10}")

    # Failures grouped by reason
    if stats.failures:
        click.echo(f"\n  Failed ({len(stats.failures)} files):")
        by_reason: dict[str, list] = {}
        for f in stats.failures:
            by_reason.setdefault(f.reason, []).append(f.file_name)
        reason_labels = {
            "too_large": "Too large",
            "permission_denied": "Permission denied",
            "export_failed": "Export failed",
            "disk_full": "Disk full",
            "download_error": "Download error",
            "unknown": "Unknown error",
        }
        for reason, files in by_reason.items():
            label = reason_labels.get(reason, reason)
            names = ", ".join(files[:5])
            if len(files) > 5:
                names += f", ... (+{len(files) - 5} more)"
            click.echo(f"    {label} ({len(files)}): {names}")

    click.echo("")
```

- [ ] **Step 4: Replace the old summary line in the run command**

In the `run` command (around line 416), replace:

```python
        click.echo(f"Backup complete: {stats.summary()}")
```

with:

```python
        _print_completion_summary(stats)
```

- [ ] **Step 5: Pass quiet flag to SyncEngine**

In `_build_engine`, accept and pass through the `quiet` parameter. Update `_build_engine`:

```python
def _build_engine(config: Config, quiet: bool = False) -> SyncEngine:
```

And in the `return SyncEngine(...)` call, add `quiet=quiet`.

In the `run` command, update the call:

```python
        engine = _build_engine(config, quiet=quiet)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_cli.py -v`
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add src/gdrive_backup/cli.py
git commit -m "feat: add rich completion summary with file types, folders, and failures"
```

---

### Task 8: JSON Log File

**Files:**
- Modify: `src/gdrive_backup/cli.py`
- Modify: `src/gdrive_backup/git_manager.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write test for gitignore management**

Add to `tests/test_git_manager.py`:

```python
class TestEnsureGitignore:
    def test_creates_gitignore_with_entry(self, tmp_path):
        repo = Repo.init(tmp_path)
        gm = GitManager(repo, tmp_path)
        gm.ensure_gitignore(".gdrive-backup/")
        gitignore = (tmp_path / ".gitignore").read_text()
        assert ".gdrive-backup/" in gitignore

    def test_appends_to_existing_gitignore(self, tmp_path):
        repo = Repo.init(tmp_path)
        (tmp_path / ".gitignore").write_text("*.pyc\n")
        gm = GitManager(repo, tmp_path)
        gm.ensure_gitignore(".gdrive-backup/")
        gitignore = (tmp_path / ".gitignore").read_text()
        assert "*.pyc" in gitignore
        assert ".gdrive-backup/" in gitignore

    def test_does_not_duplicate_entry(self, tmp_path):
        repo = Repo.init(tmp_path)
        (tmp_path / ".gitignore").write_text(".gdrive-backup/\n")
        gm = GitManager(repo, tmp_path)
        gm.ensure_gitignore(".gdrive-backup/")
        gitignore = (tmp_path / ".gitignore").read_text()
        assert gitignore.count(".gdrive-backup/") == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_git_manager.py::TestEnsureGitignore -v`
Expected: FAIL — `ensure_gitignore` not defined.

- [ ] **Step 3: Implement ensure_gitignore in GitManager**

Add to `GitManager` in `src/gdrive_backup/git_manager.py`:

```python
    def ensure_gitignore(self, entry: str) -> None:
        """Ensure an entry exists in .gitignore, creating the file if needed."""
        gitignore_path = self._path / ".gitignore"
        if gitignore_path.exists():
            content = gitignore_path.read_text()
            if entry in content.splitlines():
                return
            if not content.endswith("\n"):
                content += "\n"
            content += entry + "\n"
        else:
            content = entry + "\n"
        gitignore_path.write_text(content)
        logger.debug(f"Added '{entry}' to .gitignore")
```

- [ ] **Step 4: Run gitignore tests**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_git_manager.py::TestEnsureGitignore -v`
Expected: PASS.

- [ ] **Step 5: Write test for JSON log writing**

Add to `tests/test_cli.py`:

```python
from gdrive_backup.cli import _write_backup_log


def test_write_backup_log_creates_file(tmp_path):
    """First run creates the log file with one entry."""
    stats = SyncStats(added=5, failed=1)
    stats.total_files = 10
    stats.end_time = stats.start_time
    stats.record_failure("bad.pdf", "f1", "Docs", "permission_denied", "403")
    stats.record_file("Photos", ".jpg", 5000, 4800)

    log_path = tmp_path / ".gdrive-backup" / "backup-log.json"
    _write_backup_log(stats, tmp_path, "full_scan")

    assert log_path.exists()
    import json
    data = json.loads(log_path.read_text())
    assert len(data) == 1
    assert data[0]["summary"]["added"] == 5
    assert data[0]["mode"] == "full_scan"
    assert len(data[0]["failures"]) == 1
    assert ".jpg" in data[0]["file_types"]


def test_write_backup_log_appends(tmp_path):
    """Subsequent runs append to the existing log."""
    import json
    log_dir = tmp_path / ".gdrive-backup"
    log_dir.mkdir()
    log_path = log_dir / "backup-log.json"
    log_path.write_text(json.dumps([{"existing": True}]))

    stats = SyncStats(added=1)
    stats.total_files = 1
    stats.end_time = stats.start_time

    _write_backup_log(stats, tmp_path, "incremental")

    data = json.loads(log_path.read_text())
    assert len(data) == 2
    assert data[0]["existing"] is True
    assert data[1]["summary"]["added"] == 1
```

- [ ] **Step 6: Run test to verify it fails**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_cli.py::test_write_backup_log_creates_file -v`
Expected: FAIL — `_write_backup_log` not importable.

- [ ] **Step 7: Implement _write_backup_log**

Add to `src/gdrive_backup/cli.py`:

```python
def _write_backup_log(stats, git_repo_path: Path, mode: str) -> None:
    """Append a JSON log entry for this backup run."""
    log_dir = Path(git_repo_path) / ".gdrive-backup"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "backup-log.json"

    # Build entry
    duration = 0
    if stats.end_time and stats.start_time:
        duration = (stats.end_time - stats.start_time).total_seconds()

    entry = {
        "timestamp": stats.start_time.isoformat() if stats.start_time else datetime.now(timezone.utc).isoformat(),
        "duration_seconds": round(duration, 1),
        "mode": mode,
        "total_files_on_drive": stats.total_files,
        "summary": {
            "added": stats.added,
            "modified": stats.modified,
            "deleted": stats.deleted,
            "skipped": stats.skipped,
            "failed": stats.failed,
        },
        "storage": {
            "drive_total_bytes": stats.drive_total_bytes,
            "local_total_bytes": stats.local_total_bytes,
        },
        "file_types": {
            ext: {"count": ft.count, "drive_bytes": ft.drive_bytes, "local_bytes": ft.local_bytes}
            for ext, ft in stats.file_types.items()
        },
        "folders": {
            path: {"file_count": fs.file_count, "drive_bytes": fs.drive_size_bytes, "local_bytes": fs.local_size_bytes}
            for path, fs in stats.folders.items()
        },
        "failures": [
            {
                "file_name": f.file_name,
                "file_id": f.file_id,
                "folder_path": f.folder_path,
                "reason": f.reason,
                "error_message": f.error_message,
            }
            for f in stats.failures
        ],
    }

    # Read existing log or start fresh
    existing = []
    if log_path.exists():
        try:
            existing = json.loads(log_path.read_text())
            if not isinstance(existing, list):
                existing = []
        except (json.JSONDecodeError, OSError):
            existing = []

    existing.append(entry)
    log_path.write_text(json.dumps(existing, indent=2))
    logger.debug(f"Backup log written to {log_path}")
```

- [ ] **Step 8: Wire log writing into the run command**

In the `run` command, after `_print_completion_summary(stats)` and before the GitHub push block, add:

```python
        # Write JSON backup log
        try:
            mode = "incremental" if stats.total_files == 0 and stats.added + stats.modified + stats.deleted > 0 else "full_scan"
            _write_backup_log(stats, config.git_repo_path, mode)
            engine.git_manager.ensure_gitignore(".gdrive-backup/")
        except Exception as e:
            logger.warning(f"Failed to write backup log: {e}")
```

Also add to the log file path reference in `_print_completion_summary`, after the failures section:

```python
    # Log file reference
    click.echo(f"  Full details: {Path('~').expanduser()}/gdrive-backup-repo/.gdrive-backup/backup-log.json")
```

Wait — we should use the actual git_repo_path. Since `_print_completion_summary` doesn't have access to config, let's pass `log_path` as a parameter. Update the signature:

```python
def _print_completion_summary(stats, log_path: Optional[str] = None) -> None:
```

And at the end, if `log_path`:

```python
    if log_path:
        click.echo(f"  Full details: {log_path}")
```

Update the call in `run`:

```python
        log_file = str(config.git_repo_path / ".gdrive-backup" / "backup-log.json")
        _print_completion_summary(stats, log_path=log_file)
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_cli.py tests/test_git_manager.py -v`
Expected: All tests PASS.

- [ ] **Step 10: Commit**

```bash
git add src/gdrive_backup/cli.py src/gdrive_backup/git_manager.py tests/test_cli.py tests/test_git_manager.py
git commit -m "feat: add JSON backup log file with auto-gitignore"
```

---

### Task 9: Unified Setup Flow — Merge setup.py into init

**Files:**
- Modify: `src/gdrive_backup/cli.py` (init command)
- Modify: `install.sh`
- Modify: `scripts/setup.py`
- Test: `tests/test_cli.py`

- [ ] **Step 1: Write test for unified init with GCP instructions and credential validation**

Add to `tests/test_cli.py`:

```python
def test_init_shows_gcp_instructions(tmp_path):
    """Init command shows GCP setup instructions."""
    runner = CliRunner()
    input_lines = "\n".join([
        "oauth",
        str(tmp_path / "creds.json"),  # credentials path (won't exist, that's ok)
        str(tmp_path / "repo"),
        str(tmp_path / "mirror"),
        "n",  # no github
    ])
    result = runner.invoke(
        main, ["init", "--config", str(tmp_path / "config.yaml")],
        input=input_lines,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    assert "Google Cloud Console" in result.output or "Google Drive API" in result.output


def test_init_validates_credentials_json(tmp_path):
    """Init validates the credentials file is a Desktop app credential."""
    # Create a web credential (should be rejected)
    web_cred = tmp_path / "web_creds.json"
    import json
    web_cred.write_text(json.dumps({"web": {"client_id": "test"}}))

    # Create a valid desktop credential
    valid_cred = tmp_path / "valid_creds.json"
    valid_cred.write_text(json.dumps({"installed": {"client_id": "test"}}))

    runner = CliRunner()
    input_lines = "\n".join([
        "oauth",
        str(web_cred),    # invalid — will be rejected
        str(valid_cred),   # valid — will be accepted
        str(tmp_path / "repo"),
        str(tmp_path / "mirror"),
        "n",  # no github
    ])
    result = runner.invoke(
        main, ["init", "--config", str(tmp_path / "config.yaml")],
        input=input_lines,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    # Verify credentials were copied to control dir
    control_dir = tmp_path / "config.yaml"
    # The config was written
    assert control_dir.exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_cli.py::test_init_shows_gcp_instructions -v`
Expected: FAIL — no GCP instructions in init output.

- [ ] **Step 3: Update the init command with GCP instructions and credential validation**

In `src/gdrive_backup/cli.py`, update the `init` command. Replace the current `init` function with:

```python
GCP_INSTRUCTIONS = """
Google Cloud Console Setup
==========================

Before you can use gdrive-backup, you need Google OAuth credentials.
Follow these steps (takes about 2 minutes):

  1. Open the Google Cloud Console and create or select a project:
     https://console.cloud.google.com/

  2. Enable the Google Drive API:
     https://console.cloud.google.com/apis/library/drive.googleapis.com
     -> Click "Enable"

  3. Create OAuth 2.0 credentials:
     https://console.cloud.google.com/apis/credentials
     -> Create Credentials -> OAuth client ID
     -> Application type: Desktop app
     -> Name it anything (e.g. "gdrive-backup")
     -> Click Create, then Download JSON

  4. Note the path to the downloaded file - you will enter it below.

"""


def _validate_credentials_json(path: Path) -> tuple:
    """Validate a Google OAuth Desktop app credentials JSON file.

    Returns (ok, error_message).
    """
    if not path.exists():
        return False, f"File not found: {path}"
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        return False, f"Invalid JSON: {e}"
    if "installed" in data:
        return True, ""
    if "web" in data:
        return False, (
            "This is a Web application credential, not a Desktop app credential.\n"
            "  Please create a new OAuth client ID with Application type: Desktop app"
        )
    if data.get("type") == "service_account":
        return False, (
            "This is a service account key, not an OAuth credential.\n"
            "  Select 'service_account' as auth method for service account setup."
        )
    return False, "Unrecognized credentials format. Expected a Desktop app OAuth credential."


@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
@click.pass_context
def init(ctx, config_path):
    """Set up a new backup configuration."""
    import shutil

    _enable_readline()
    control_dir = _resolve_control_dir(config_path)
    control_dir.mkdir(parents=True, exist_ok=True)
    (control_dir / "logs").mkdir(exist_ok=True)

    config_file = control_dir / "config.yaml"

    if config_file.exists():
        click.echo(f"Config already exists at {config_file}")
        if not click.confirm("Overwrite?"):
            return

    # Show GCP instructions
    click.echo(GCP_INSTRUCTIONS)

    # Auth method
    auth_method = _prompt_text("Authentication method (oauth/service_account)", "oauth")

    # Credentials file with validation
    creds_path = None
    for attempt in range(3):
        creds_input = _prompt_path(
            "Path to credentials JSON file",
            str(control_dir / "credentials.json"),
        )
        creds_path = Path(creds_input).expanduser()

        if not creds_path.exists():
            click.echo(f"  Note: File not found at {creds_path}. You can place it there later.")
            break

        if auth_method == "oauth":
            ok, error = _validate_credentials_json(creds_path)
            if ok:
                # Copy to control dir
                dest = control_dir / "credentials.json"
                if creds_path != dest:
                    shutil.copy2(creds_path, dest)
                    dest.chmod(0o600)
                    click.echo(f"  Credentials copied to {dest}")
                creds_path = dest
                break
            else:
                click.echo(f"  Error: {error}")
                if attempt < 2:
                    click.echo("  Please try again.\n")
        else:
            break
    else:
        click.echo("  Too many failed attempts. You can place the credentials file manually.")
        creds_path = control_dir / "credentials.json"

    # Backup paths
    git_repo_path = _prompt_path("Git repo path (for text files)", str(Path.home() / "gdrive-backup-repo"))
    mirror_path = _prompt_path("Mirror path (for binary files)", str(Path.home() / "gdrive-backup-mirror"))

    # Build config dict
    config_data = {
        "auth": {
            "method": auth_method,
            "credentials_file": creds_path.name if creds_path.parent == control_dir else str(creds_path),
            "token_file": "token.json",
        },
        "backup": {
            "git_repo_path": git_repo_path,
            "mirror_path": mirror_path,
        },
        "scope": {
            "include_shared": False,
            "folder_ids": [],
        },
        "sync": {
            "state_file": "state.json",
        },
        "max_file_size_mb": 0,
        "logging": {
            "max_size_mb": 10,
            "max_files": 5,
            "default_level": "info",
        },
        "daemon": {
            "poll_interval": 300,
        },
    }

    # GitHub setup
    github_data = None
    if click.confirm("\nEnable GitHub push?", default=False):
        gh_pat = _prompt_text("  GitHub PAT (leave blank to use GITHUB_PAT env var)")

        if gh_pat:
            # Validate PAT before asking for other details
            click.echo("  Validating PAT...")
            try:
                # Temporary manager just for validation
                temp_mgr = GithubManager(gh_pat, "test", "test")
                temp_mgr.validate_pat()
                click.echo("  PAT validated successfully.")
            except GithubError as e:
                click.echo(f"  Warning: PAT validation failed: {e}")
                if not click.confirm("  Continue anyway?", default=False):
                    gh_pat = ""

        gh_owner = _prompt_text("  GitHub owner (user or org)")
        gh_repo = _prompt_text("  Repository name", "gdrive-backup-data")
        gh_private = click.confirm("  Private repo?", default=True)
        gh_auto_create = click.confirm("  Auto-create if missing?", default=True)

        github_data = {
            "enabled": True,
            "pat": gh_pat,
            "owner": gh_owner,
            "repo": gh_repo,
            "private": gh_private,
            "auto_create": gh_auto_create,
        }

    if github_data:
        config_data["github"] = github_data

    with open(config_file, "w") as f:
        yaml.dump(config_data, f, default_flow_style=False)
    os.chmod(config_file, 0o600)

    # Initialize git repo
    git_path = Path(git_repo_path).expanduser()
    GitManager.init_repo(git_path)

    # Create mirror directory
    Path(mirror_path).expanduser().mkdir(parents=True, exist_ok=True)

    click.echo(f"\nSetup complete!")
    click.echo(f"  Config: {config_file}")
    click.echo(f"  Git repo: {git_path}")
    click.echo(f"  Mirror: {mirror_path}")
    click.echo(f"\nTo start your first backup, run: gdrive-backup run")
```

- [ ] **Step 4: Update install.sh to use gdrive-backup init**

Replace the setup wizard section at the end of `install.sh` (lines 161-168):

```bash
# ── Launch configuration wizard ─────────────────────────────────────────────
info "Launching configuration wizard..."
echo ""
gdrive-backup init </dev/tty
```

- [ ] **Step 5: Deprecate scripts/setup.py**

Replace `scripts/setup.py` content with a thin wrapper:

```python
#!/usr/bin/env python3
"""DEPRECATED — use 'gdrive-backup init' directly.

This script is kept for backwards compatibility with older install.sh URLs.
"""
import subprocess
import sys


def main():
    print("Note: scripts/setup.py is deprecated. Running 'gdrive-backup init' instead.\n")
    result = subprocess.run(["gdrive-backup", "init"], check=False)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_cli.py tests/test_setup.py -v`
Expected: All tests PASS. (Some test_setup.py tests may need updating if they test the old setup.py logic — check and fix if needed.)

- [ ] **Step 7: Commit**

```bash
git add src/gdrive_backup/cli.py install.sh scripts/setup.py tests/test_cli.py
git commit -m "feat: unify setup flow — merge scripts/setup.py into gdrive-backup init"
```

---

### Task 10: PAT Validation Tests

**Files:**
- Modify: `tests/test_github_manager.py`

- [ ] **Step 1: Add PAT validation edge case tests**

Add to `tests/test_github_manager.py`:

```python
class TestValidatePatEdgeCases:
    def test_validate_pat_with_empty_string_raises(self):
        """Empty PAT should fail validation."""
        mgr = GithubManager(pat="", owner="alice", repo="backup")
        with patch.object(mgr._session, "get", return_value=_mock_response(401)):
            with pytest.raises(GithubError, match="Invalid PAT"):
                mgr.validate_pat()

    def test_validate_pat_network_error_raises(self):
        """Network error during validation should raise."""
        mgr = GithubManager(pat="test_pat", owner="alice", repo="backup")
        with patch.object(mgr._session, "get", side_effect=req.ConnectionError("network down")):
            with pytest.raises(req.ConnectionError):
                mgr.validate_pat()

    def test_validate_pat_timeout_raises(self):
        """Timeout during validation should raise."""
        mgr = GithubManager(pat="test_pat", owner="alice", repo="backup")
        with patch.object(mgr._session, "get", side_effect=req.Timeout("timed out")):
            with pytest.raises(req.Timeout):
                mgr.validate_pat()
```

Also add the import at the top:

```python
import requests as req
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/test_github_manager.py -v`
Expected: All tests PASS (these are new tests for existing functionality).

- [ ] **Step 3: Commit**

```bash
git add tests/test_github_manager.py
git commit -m "test: add PAT validation edge case tests (empty, network error, timeout)"
```

---

### Task 11: Final Integration Test

**Files:**
- Test: `tests/test_cli.py`

- [ ] **Step 1: Run the full test suite**

Run: `cd /home/eyal/repos/google-drive-backup && python -m pytest tests/ -v`
Expected: All tests PASS.

- [ ] **Step 2: Fix any failures**

If any tests fail, fix them. Common issues:
- Existing tests that mock `SyncStats` may need updating since the constructor now has more default fields
- The `_build_engine` call in test mocks may need the `quiet` parameter
- Import paths may need updating for new symbols

- [ ] **Step 3: Final commit if any fixes were needed**

```bash
git add -A
git commit -m "fix: resolve test integration issues from v0.2.0 changes"
```
