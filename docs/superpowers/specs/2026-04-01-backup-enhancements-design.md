# Backup Enhancements Design Spec

**Date**: 2026-04-01
**Version**: 0.1.0 -> 0.2.0

## Overview

Four enhancements to improve the backup experience: rich post-backup summary, persistent JSON log, unified setup flow with GitHub PAT, and live progress display with ETA.

## 1. Unified Setup Flow

### Problem
Two separate setup scripts exist: `scripts/setup.py` (GCP credentials) and `gdrive-backup init` (config/GitHub). Users go from install to `run` without ever hitting the full setup, missing GitHub PAT configuration entirely.

### Solution
Merge `scripts/setup.py` logic into `gdrive-backup init`. Single flow:

1. Print GCP setup instructions (from `scripts/setup.py`)
2. Prompt for credentials JSON path (validate: must be Desktop OAuth app, 3 retries)
3. Copy credentials to `~/.gdrive-backup/credentials.json` (chmod 600)
4. Prompt for backup paths (git repo, mirror)
5. Prompt for scope (include shared files? specific folder IDs?)
6. Prompt: "Do you want to push backups to GitHub? [y/N]"
   - If yes: prompt for PAT, validate via `GithubManager.validate_pat()`, prompt for owner/repo/private
   - If validation fails: show error, retry or skip
7. Write `config.yaml` (chmod 600)
8. Run OAuth flow to get token
9. Print: "Setup complete. Run `gdrive-backup run` for your first backup."

### File changes
- `src/gdrive_backup/cli.py`: Merge setup.py logic into `init` command
- `install.sh`: Replace `scripts/setup.py` download+run with `gdrive-backup init`
- `scripts/setup.py`: Deprecate — thin wrapper that calls `gdrive-backup init`

## 2. Enriched SyncStats + Failure Tracking

### Approach
Enrich the existing `SyncStats` dataclass to carry all new data. The sync engine populates it during processing; the CLI reads it for display and logging.

### New data structures

```python
@dataclass
class FailureRecord:
    file_name: str
    file_id: str
    folder_path: str
    reason: str          # "too_large", "export_failed", "permission_denied", "disk_full", "download_error", "unknown"
    error_message: str   # raw exception message

@dataclass
class FolderStats:
    file_count: int
    drive_size_bytes: int
    local_size_bytes: int

@dataclass
class FileTypeStats:
    count: int
    drive_bytes: int
    local_bytes: int

@dataclass
class SyncStats:
    # existing
    added: int
    modified: int
    deleted: int
    skipped: int
    failed: int

    # new
    total_files: int                     # from count query
    folders: Dict[str, FolderStats]      # folder path -> stats
    file_types: Dict[str, FileTypeStats]  # extension -> {count, drive_bytes, local_bytes}
    failures: List[FailureRecord]        # detailed failure info
    start_time: datetime
    end_time: Optional[datetime]
    drive_total_bytes: int               # sum of Drive file sizes
    local_total_bytes: int               # sum of local file sizes
```

### Failure categorization
In `_process_file()`, classify exceptions into reason categories before appending to `stats.failures`:
- File size check fails -> "too_large"
- Disk space check fails -> "disk_full"
- Download HTTP 403 -> "permission_denied"
- Export errors -> "export_failed"
- Download errors -> "download_error"
- Everything else -> "unknown"

### Folder/type accumulation
As each file is processed successfully, update `stats.folders[path]` and `stats.file_types[ext]` with counts and sizes (both Drive and local).

## 3. Live Progress Counter

### Two-pass approach

**Pass 1 — Count**: New `DriveClient.count_files()` method. Same query as `list_all_files()` but requests only `files(id)` via `fields` parameter. Pages through to get exact total. Stored in `stats.total_files`.

**Pass 2 — Process**: Existing `list_all_files()` + `_process_file()` loop, with progress callbacks.

### Progress display

`ProgressTracker` class in `sync_engine.py`:

```
[  347/3120]  11% |####                                | 2m 14s remaining - downloading invoice.pdf
```

Shows:
- Files processed / total
- Percentage
- Progress bar
- ETA (rolling average of per-file processing time)
- Current file name

Implementation:
- `tracker.update(file_name)` called after each file
- ETA from elapsed time / files processed * files remaining
- `\r` overwrites same line on stderr
- Suppressed in quiet mode
- Non-TTY: periodic log lines ("Processed 500/3120 files...")

### Completion summary (stdout)

```
Backup complete in 4m 32s

  Files: 2644 added, 0 modified, 0 deleted, 472 skipped, 4 failed
  Storage: 1.8 GB on Drive -> 1.6 GB local

  By type:
    Photos (.jpg, .png, .heic)    1,847 files    1.2 GB
    Documents (.docx, .pdf)         412 files  230.5 MB
    Spreadsheets (.xlsx)             89 files   45.2 MB
    Other                           296 files  124.3 MB

  Top folders (10):
    My Drive/Photos/2025           847 files  620.1 MB
    My Drive/Work/Projects         234 files  180.4 MB
    My Drive/Documents             189 files   95.2 MB
    ...

  Failed (4 files):
    Too large (2): budget_video.mp4, presentation_recording.mov
    Permission denied (1): shared_report.docx
    Export failed (1): corrupted_form.gdoc

  Full details: ~/gdrive-backup-repo/.gdrive-backup/backup-log.json
```

Top 10 folders in terminal; full list in log file. File types grouped into human-friendly categories using classifier knowledge.

## 4. JSON Log File

### Location
`{git_repo_path}/.gdrive-backup/backup-log.json`

### Gitignore
Auto-add `.gdrive-backup/` to `{git_repo_path}/.gitignore` on first run. Create file if needed, append if entry is missing.

### Format
JSON array, one entry appended per run:

```json
[
  {
    "timestamp": "2026-03-31T11:07:41Z",
    "duration_seconds": 272,
    "mode": "full_scan",
    "total_files_on_drive": 3120,
    "summary": {
      "added": 2644,
      "modified": 0,
      "deleted": 0,
      "skipped": 472,
      "failed": 4
    },
    "storage": {
      "drive_total_bytes": 1932735283,
      "local_total_bytes": 1718042624
    },
    "file_types": {
      ".jpg": { "count": 1203, "drive_bytes": 892341200, "local_bytes": 892341200 },
      ".png": { "count": 412, "drive_bytes": 234500000, "local_bytes": 234500000 },
      ".docx": { "count": 89, "drive_bytes": 45200000, "local_bytes": 43100000 }
    },
    "folders": {
      "My Drive/Photos/2025": { "file_count": 847, "drive_bytes": 650100000, "local_bytes": 620100000 },
      "My Drive/Work/Projects": { "file_count": 234, "drive_bytes": 190400000, "local_bytes": 180400000 }
    },
    "failures": [
      {
        "file_name": "budget_video.mp4",
        "file_id": "abc123",
        "folder_path": "My Drive/Videos",
        "reason": "too_large",
        "error_message": "File size 2.1 GB exceeds limit of 100 MB"
      }
    ]
  }
]
```

### Write strategy
Read existing array, append new entry, write back. If file is corrupt or missing, start a fresh array.

## 5. PAT Validation Tests

New tests in `tests/test_github_manager.py`:

- `test_validate_pat_success` — mock `GET /user` returning 200 with scopes, assert passes
- `test_validate_pat_invalid` — mock `GET /user` returning 401, assert raises `GithubError`
- `test_validate_pat_missing_scopes` — mock `GET /user` returning 200 but missing `repo` scope, assert raises with helpful message

## 6. Version Bump

`pyproject.toml`: 0.1.0 -> 0.2.0

## Files Modified

| File | Change |
|---|---|
| `src/gdrive_backup/sync_engine.py` | Enrich `SyncStats`, add `FailureRecord`, `FolderStats`, `ProgressTracker`, folder/type accumulation |
| `src/gdrive_backup/drive_client.py` | Add `count_files()` method |
| `src/gdrive_backup/cli.py` | Merge setup.py into `init`, GitHub PAT prompt, rich completion summary, log file writing, progress display |
| `src/gdrive_backup/git_manager.py` | Auto-manage `.gitignore` for `.gdrive-backup/` |
| `install.sh` | Replace `scripts/setup.py` with `gdrive-backup init` |
| `scripts/setup.py` | Deprecate — thin wrapper calling `gdrive-backup init` |
| `tests/test_github_manager.py` | PAT validation tests |
| `tests/test_sync_engine.py` | Tests for enriched stats, failure categorization |
| `tests/test_cli.py` | Tests for new init flow, completion summary |
| `pyproject.toml` | Version bump to 0.2.0 |
