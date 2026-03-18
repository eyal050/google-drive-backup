# Google Drive Backup

Back up your entire Google Drive to your local machine — text files go into a **git repository** (with full version history), binary files go into a **mirror directory**.

Optionally, push the git repo to a private GitHub repository automatically after each backup.

---

## How it works

| File type | Where it goes | Why |
|-----------|--------------|-----|
| Text files (docs, code, markdown, etc.) | Git repository | Version history, diffs |
| Binary files (images, PDFs, videos, etc.) | Mirror directory | Plain copy, no git bloat |

Google Docs, Sheets, and Slides are exported to text-friendly formats (`.docx`, `.xlsx`, `.pptx`) and stored in the git repo.

---

## Prerequisites

- Python 3.10 or newer
- Git installed and on your PATH
- A Google account with Drive access

---

## Installation

```bash
pip install gdrive-backup
```

Or from source:

```bash
git clone https://github.com/eyal050/google-drive-backup
cd google-drive-backup
pip install .
```

Verify the install:

```bash
gdrive-backup --version
```

---

## Step 1 — Get Google API credentials

Before you can use this tool, you need to create a Google Cloud project and download a credentials file.

1. Go to [Google Cloud Console](https://console.cloud.google.com/) and create a new project (or use an existing one).
2. Enable the **Google Drive API**:
   - In the left menu, go to **APIs & Services → Library**
   - Search for "Google Drive API" and click **Enable**
3. Create OAuth credentials:
   - Go to **APIs & Services → Credentials**
   - Click **Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
   - Click **Create**, then **Download JSON**
4. Save the downloaded file as `credentials.json` — you'll need it in the next step.

---

## Step 2 — Run setup

```bash
gdrive-backup init
```

This interactive wizard will ask you:

- **Authentication method** — choose `oauth` (recommended for personal use)
- **Path to credentials JSON** — the file you downloaded in Step 1
- **Git repo path** — where text files will be stored (default: `~/gdrive-backup-repo`)
- **Mirror path** — where binary files will be stored (default: `~/gdrive-backup-mirror`)
- **Enable GitHub push?** — optional, see [GitHub push](#optional-github-push) below

The config is saved to `~/.gdrive-backup/config.yaml`.

---

## Step 3 — Run your first backup

```bash
gdrive-backup run
```

The first time you run this, a browser window will open asking you to sign in to Google and grant access. After you approve, a `token.json` file is saved so future runs don't need the browser.

**Want to preview what would be backed up without writing anything?**

```bash
gdrive-backup run --dry-run
```

---

## Day-to-day operations

### Run a backup

```bash
gdrive-backup run
```

### Check backup status

```bash
gdrive-backup status
```

Shows the last run time, status, and how many files are being tracked.

### View current configuration

```bash
gdrive-backup config
```

### Run continuously (daemon mode)

Keeps running in the background, checking for changes at a regular interval:

```bash
gdrive-backup daemon
```

The default poll interval is 300 seconds (5 minutes). Change it in the config file under `daemon.poll_interval`.

Press **Ctrl+C** to stop.

### Verbose output

```bash
gdrive-backup run --verbose    # Show INFO logs in terminal
gdrive-backup run --debug      # Show all logs (very detailed)
gdrive-backup run --quiet      # Only show errors
```

---

## Config file reference

The config file lives at `~/.gdrive-backup/config.yaml`. Here is a full example with explanations:

```yaml
# Authentication
auth:
  method: oauth                  # "oauth" (personal) or "service_account" (automated)
  credentials_file: credentials.json   # Path to Google API credentials
  token_file: token.json         # Saved OAuth token (auto-created on first login)

# Where to store backups
backup:
  git_repo_path: ~/gdrive-backup-repo    # Text files go here (git repo)
  mirror_path: ~/gdrive-backup-mirror    # Binary files go here (plain copy)

# What to back up
scope:
  include_shared: false          # Set to true to also back up files shared with you
  folder_ids: []                 # Leave empty to back up all of Drive.
                                 # To back up specific folders only, add their IDs:
                                 # folder_ids:
                                 #   - "1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms"

# Sync settings
sync:
  state_file: state.json         # Tracks which files have been backed up

# File size limit (0 = no limit)
max_file_size_mb: 0

# Logging
logging:
  max_size_mb: 10               # Max size of each log file
  max_files: 5                  # How many log files to keep
  default_level: info           # "debug", "info", "warning", or "error"

# Daemon mode
daemon:
  poll_interval: 300            # Seconds between backup checks

# GitHub push (optional)
github:
  enabled: false
  pat: ""                       # GitHub Personal Access Token (or use GITHUB_PAT env var)
  owner: "your-github-username"
  repo: "gdrive-backup-data"
  private: true
  auto_create: true             # Create the repo automatically if it doesn't exist
```

---

## Optional: GitHub push

You can automatically push the git repo to a private GitHub repository after each backup.

**Setup:**

1. Create a [GitHub Personal Access Token](https://github.com/settings/tokens) with `repo` scope.
2. Run `gdrive-backup init` (or edit your config) and enable GitHub push.
3. Either put the token in `github.pat` in the config, or set it as an environment variable:

```bash
export GITHUB_PAT=ghp_your_token_here
gdrive-backup run
```

Using the environment variable is more secure since the token won't be stored in the config file.

---

## How to find a Google Drive folder ID

To back up only specific folders, you need their folder IDs.

1. Open Google Drive in your browser and navigate to the folder.
2. Look at the URL: `https://drive.google.com/drive/folders/`**`1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms`**
3. Copy the long string after `/folders/` — that's the folder ID.
4. Add it to `scope.folder_ids` in your config.

---

## File locations

| File | Default path | Purpose |
|------|-------------|---------|
| Config | `~/.gdrive-backup/config.yaml` | All settings |
| Credentials | `~/.gdrive-backup/credentials.json` | Google API credentials |
| Token | `~/.gdrive-backup/token.json` | Saved OAuth login |
| State | `~/.gdrive-backup/state.json` | Tracks backed-up files |
| Logs | `~/.gdrive-backup/logs/` | Log files |
| Git repo | `~/gdrive-backup-repo/` | Backed-up text files |
| Mirror | `~/gdrive-backup-mirror/` | Backed-up binary files |

---

## Command reference

```
gdrive-backup init        Set up a new backup configuration (interactive)
gdrive-backup run         Run a single backup
gdrive-backup run -n      Dry run — preview what would be backed up
gdrive-backup run -v      Run with verbose output
gdrive-backup run --debug Run with maximum log detail
gdrive-backup status      Show last backup status
gdrive-backup config      Show current configuration
gdrive-backup daemon      Run continuously in the background
```

---

## License

MIT
