# Google Drive Backup — Design Specification

## Overview

A Python CLI tool that backs up an entire Google Drive account to local storage. Text files are stored in a **git repository** (providing built-in version history), while binary files are stored in a separate **mirror directory**. The tool supports manual runs, cron scheduling, and continuous daemon mode.

**Goals:**
- Complete backup of a Google Drive account with version history for text files
- Simple setup and minimal ongoing user interaction
- Open-source friendly — clean code, good docs, easy to contribute to

---

## Architecture

**Approach: Core Library + CLI Shell**

A clean separation between a core library (handles Drive API, file classification, download, git operations, mirror management) and a thin CLI layer (handles user interaction, scheduling, daemon mode).

### Project Structure

```
google-drive-backup/
├── src/
│   └── gdrive_backup/
│       ├── __init__.py
│       ├── cli.py              # CLI entry point (click-based)
│       ├── config.py           # Configuration loading/validation
│       ├── auth.py             # OAuth 2.0 + service account auth
│       ├── drive_client.py     # Google Drive API wrapper
│       ├── classifier.py       # File type classification (MIME + content detection)
│       ├── git_manager.py      # Git repo operations
│       ├── mirror_manager.py   # Binary file mirror operations
│       ├── sync_engine.py      # Orchestrates the backup process
│       └── daemon.py           # Daemon/watch mode
├── tests/
│   └── ...
├── config.example.yaml         # Example configuration
├── pyproject.toml              # Project metadata + dependencies
├── .gitignore
└── README.md
```

### Key Dependencies

- `google-api-python-client` + `google-auth` + `google-auth-oauthlib` — Drive API and authentication
- `click` — CLI framework
- `gitpython` — Git operations
- `python-magic` — Content-based file type detection
- `pyyaml` — Configuration parsing

---

## Authentication

Supports two methods:

1. **OAuth 2.0** — Browser-based consent flow for end users. User registers a Google Cloud project and provides client credentials.
2. **Service account** — JSON key file for personal/server use. Simpler but less intuitive for other users.

Both are supported. The `init` command guides the user through setup.

### Security

- Credentials and tokens stored with `600` file permissions
- Token refresh handled automatically
- Credential file existence and permissions validated on startup
- Minimum OAuth scope: `drive.readonly`

---

## Configuration

Stored at `~/.gdrive-backup/config.yaml`:

```yaml
# Authentication
auth:
  method: oauth  # "oauth" or "service_account"
  credentials_file: credentials.json
  token_file: token.json

# Backup targets
backup:
  git_repo_path: ~/gdrive-backup-repo
  mirror_path: ~/gdrive-backup-mirror

# What to back up
scope:
  include_shared: false
  folder_ids: []  # Empty = entire Drive

# Sync settings
sync:
  state_file: ~/.gdrive-backup/state.json

# File size limit (0 = no limit)
max_file_size_mb: 0  # Skip files larger than this (in MB)

# Logging
logging:
  max_size_mb: 10       # Max log file size before rotation
  max_files: 5          # Number of rotated log files to keep
  default_level: info   # Default log level (debug, info, warning, error)

# Daemon mode
daemon:
  poll_interval: 300  # Seconds between checks
```

### Control Directory

```
~/.gdrive-backup/
├── config.yaml
├── state.json
├── token.json
├── logs/
│   ├── gdrive-backup.log
│   └── gdrive-backup.log.1  # Rotated
└── credentials.json
```

Kept separate from backup data to prevent credentials from being accidentally committed to git.

### Config Path Resolution

- **Auth-related paths** (`credentials_file`, `token_file`, `state_file`): resolved relative to the control directory (`~/.gdrive-backup/`)
- **Backup paths** (`git_repo_path`, `mirror_path`): must be absolute or use `~` expansion

### Config Security

- Validate backup paths are absolute (after `~` expansion) and within expected boundaries
- Warn if config file permissions are too open

---

## File Classification

**Two-stage classification to determine text vs binary:**

1. **MIME type from Google Drive API** (primary) — Google returns MIME types for every file. Text types include: `text/*`, `application/json`, `application/xml`, `application/javascript`, `application/x-yaml`, `application/x-sh`, `application/sql`, and other known text MIME types. Binary types include: `image/*`, `application/pdf`, `video/*`, `audio/*`, `application/zip`, `application/octet-stream`, and Microsoft Office formats. A comprehensive default allowlist is maintained in `classifier.py`.
2. **Content detection** (fallback) — Using `python-magic` to inspect file contents when MIME type is ambiguous.

**Persistent cache:** Classification results are cached in `state.json`. The first run classifies every file (heavy). Subsequent runs only classify new or changed files.

### Google Native File Exports

Google Docs, Sheets, and Slides are cloud-only — they must be exported:

| Google Format | Export As | Destination |
|---|---|---|
| Google Docs | `.docx` | Mirror |
| Google Sheets | `.xlsx` | Mirror |
| Google Slides | `.pptx` | Mirror |

These are binary formats, so they go to the mirror directory.

**Trade-off note:** Exporting as Microsoft formats means Google Docs/Sheets/Slides won't benefit from git version history. This is an intentional decision — Microsoft formats preserve full fidelity (formatting, embedded objects, formulas) which is more important for a backup tool than diffability. Users who need git-tracked Google Docs can re-export manually.

### Duplicate File Name Resolution

Google Drive allows multiple files with the same name in the same folder. When constructing local paths:

1. First file with a given name gets the clean path: `documents/report.docx`
2. Subsequent files with the same name get a Drive file ID suffix: `documents/report (1aBcDeFgHiJ).docx`
3. The mapping is stable — once a file gets a suffix, it keeps it across runs (tracked in the file cache)
4. This applies to both git repo and mirror directory paths

### Classifier Security

- Sanitize file names to prevent path traversal (e.g., `../../etc/passwd`)
- Validate MIME types against an allowlist

---

## Core Modules

### Data Flow

```
1. Auth          → Get authenticated Drive API client
2. Detect changes → First run: full scan. Subsequent: changes API
3. For each changed file:
   a. Classify   → Check cache → MIME type → content detection → cache result
   b. Download   → Google native files: export as .docx/.xlsx/.pptx
                    Regular files: download as-is
   c. Route      → Text file? → git_repo_path (git add + commit)
                    Binary file? → mirror_path
4. Handle deletes → Remove locally, git commit if in repo
5. Save state    → Update change token + classification cache
```

### Module Responsibilities

| Module | Does | Doesn't |
|---|---|---|
| `auth.py` | Returns an authenticated API client | Know about files or sync |
| `drive_client.py` | Lists files, detects changes, downloads/exports | Know where files go locally |
| `classifier.py` | Decides text vs binary, caches results | Download or move files |
| `git_manager.py` | Adds/removes/commits files in the git repo | Talk to Drive API |
| `mirror_manager.py` | Writes/deletes files in mirror directory | Talk to Drive API |
| `sync_engine.py` | Orchestrates the full backup flow | Handle CLI args or daemon loops |
| `config.py` | Loads/validates configuration | Contain business logic |
| `cli.py` | Parses commands, calls sync_engine | Contain business logic |
| `daemon.py` | Runs sync_engine on an interval | Contain business logic |

### Module Security

| Module | Security measures |
|---|---|
| `auth.py` | Credentials/tokens stored with `600` permissions. Auto token refresh. Validate credential files on startup. |
| `drive_client.py` | Minimum OAuth scopes (`drive.readonly`). Proactive rate limiting (see below). Validate API responses. |
| `classifier.py` | Sanitize file names (path traversal prevention). Validate MIME types against allowlist. |
| `git_manager.py` | Sanitize file paths. Reject symlinks. Validate repo integrity before commits. |
| `mirror_manager.py` | Path sanitization. Enforce writes only within mirror directory. Safe file permissions (`644`). |
| `sync_engine.py` | Validate config before starting. Atomic operations (download to temp, then move). Catch and log errors without crashing. |
| `config.py` | Validate paths are absolute and within boundaries. Warn on open permissions. |
| `daemon.py` | PID file to prevent duplicate instances. Graceful shutdown on SIGTERM/SIGINT. |

### API Rate Limiting & Quota Management

Google Drive API has a default quota of 12,000 queries per 100 seconds per project. The `drive_client.py` module implements proactive throttling:

- **Request rate cap:** Maximum 100 requests/second (well under quota)
- **Batch API usage:** Use batch requests for file metadata queries during full scans (up to 100 per batch)
- **Reactive throttling:** On HTTP 429, respect `Retry-After` header and reduce rate cap by 50% for the remainder of the run
- **Progress reporting:** During long operations (full scan, large incremental), log progress every 100 files: `"Processing file 1,234 of 5,678 (22%)"`

### Git Commit Strategy

Each sync run produces a single commit with all changes:
`"Backup 2026-03-17T14:30:00 — 12 files added, 3 modified, 1 deleted"`

---

## Incremental Sync & State Management

### First Run — Full Scan

1. Call `files.list` to enumerate entire Drive (paginated)
2. Download and classify every file
3. Save the `startPageToken` from Drive's changes API
4. Save classification cache

### Subsequent Runs — Incremental

1. Load `startPageToken` from `state.json`
2. Call `changes.list` to get only what changed since last run
3. For each change:
   - **New file:** classify, download, route
   - **Modified file:** re-download, re-classify (type could change), route
   - **Deleted file:** remove from git repo or mirror, update cache
   - **Moved/renamed file:** move locally to match new path, git commit the move
4. Save new `startPageToken` and updated cache

### State File Structure

```json
{
  "start_page_token": "12345",
  "last_run": "2026-03-17T14:30:00Z",
  "last_run_status": "success",
  "file_cache": {
    "drive_file_id_1": {
      "type": "text",
      "mime": "text/plain",
      "local_path": "documents/notes.txt",
      "md5": "abc123...",
      "last_modified": "2026-03-17T10:00:00Z"
    }
  }
}
```

### Resilience

- `startPageToken` only updated after successful completion — interrupted runs replay safely
- Individual file failures logged but don't stop the run
- MD5 checksums from Drive API compared to detect corruption

---

## CLI Interface

```
gdrive-backup [OPTIONS] COMMAND

Commands:
  init          Set up a new backup (creates ~/.gdrive-backup/,
                initializes git repo and mirror directory, runs auth flow)
  run           Run a single backup (manual or cron-friendly)
  daemon        Start continuous backup mode
  status        Show backup status (last run, file counts, etc.)
  config        Show or edit configuration

Options:
  --config PATH    Override config file location
  --verbose / -v   Increase log verbosity
  --debug          Maximum verbosity
  --quiet / -q     Suppress console output (still logs to file)
```

### `init` Flow

1. Create `~/.gdrive-backup/` structure
2. Prompt for auth method (OAuth or service account)
3. Run auth flow, store credentials
4. Ask for git repo path and mirror path (or use defaults)
5. Initialize git repo at the configured path
6. Write `config.yaml`
7. Print summary and suggest running `gdrive-backup run` to start first backup

### Exit Codes

- `0` — Success
- `1` — Partial failure (some files failed, logged)
- `2` — Fatal error (auth failure, config invalid, etc.)

### Cron Example

```bash
# Daily backup at 2 AM
0 2 * * * gdrive-backup run --quiet
```

---

## Logging

- **Location:** `~/.gdrive-backup/logs/` with rotating file logs (configurable max size + retention)
- **Console:** Configurable verbosity (`--quiet`, default, `--verbose`, `--debug`)
- **Format:** `TIMESTAMP [MODULE] LEVEL MESSAGE`
- **Examples:**
  - `2026-03-17 14:30:12 [sync_engine] INFO  Downloaded "Q3 Report.docx" (1.2MB) → mirror`
  - `2026-03-17 14:30:13 [classifier] DEBUG MIME=text/plain, content_check=text → git repo`

---

## Error Handling

### Retry Strategy

- API calls: exponential backoff (1s, 2s, 4s, 8s) with max 3 retries
- Rate limit errors (HTTP 429): respect `Retry-After` header
- Network errors: retry with backoff, log and skip file after max retries

### Failure Modes

| Failure | Behavior |
|---|---|
| Auth token expired | Auto-refresh. If refresh fails, prompt re-auth on next manual run. Daemon logs error and retries next cycle. |
| Single file download fails | Log error, skip file, continue. Retried on next run. |
| Git commit fails | Log error, leave files staged. Next run includes them. |
| Disk full | Detect before writing (check available space), abort with clear error. |
| Interrupted mid-run | State not updated — next run replays same changes (idempotent). |
| Corrupt state file | Detect via JSON validation. Fall back to full scan, rebuild cache. |
| Duplicate file names | Append Drive file ID suffix, e.g., `report (abc123).docx`. Log warning. |

### Idempotency

Every operation is safe to repeat. Downloading the same file twice produces the same result. Git won't create empty commits if nothing changed.

---

## Scope & Shared Files

- **Default:** Only files owned by the authenticated user
- **Configurable:** `include_shared: true` in config to also back up files in "Shared with me"
- **Folder scoping:** Optional `folder_ids` list to limit backup to specific folders

## Conflict Handling

- **Last write wins** — this is a one-way backup (Drive → local), not a sync. Whatever Drive has is correct.

---

## Restoring Files

This tool is backup-only — it does not sync files back to Google Drive. To restore:

- **Text files (git repo):** Use standard git commands. `git log` to find versions, `git checkout <commit> -- <file>` to restore a specific version.
- **Binary files (mirror):** Copy files directly from the mirror directory. The mirror reflects the latest state of Drive at the time of the last backup.
- **Full restore:** Copy both the git repo contents and mirror directory contents to the desired location.

A dedicated `restore` command may be added in a future version.

---

## Out of Scope (Future Considerations)

- **Google Workspace Shared Drives** (Team Drives) — these use a different API surface (`supportsAllDrives`, `driveId`). Not supported in v1.
- **Two-way sync** — this is a backup tool, not a sync tool.
- **Git LFS** — binary files may be migrated to LFS in a future version for versioning.
- **Encryption** — local backups are stored unencrypted. Users can layer encryption on top.
