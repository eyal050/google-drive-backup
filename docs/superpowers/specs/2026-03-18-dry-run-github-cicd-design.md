# Dry Run, GitHub Connector, and CI/CD — Design Specification

## Overview

Three new capabilities added to `gdrive-backup`:

1. **Dry run mode** — enumerate Drive files and report counts/sizes without writing anything
2. **GitHub connector** — push the local git backup to a GitHub repository after each run
3. **CI/CD pipelines** — unit test CI on every push/PR; real end-to-end backup workflow on demand

A fourth deliverable is a **cleanup script** to delete e2e test outputs (GitHub repos/branches + local dirs).

---

## 1. Dry Run

### CLI

`gdrive-backup run --dry-run` (alias `-n`) performs a read-only preview run. GitHub push is always skipped in dry run mode (see run flow in section 2).

### Behaviour

1. Load and validate config (same as normal run).
2. Attempt Google Drive authentication and enumerate all files via API. OAuth token refresh (writing `token.json`) **is permitted** in dry-run mode — it is a credential maintenance operation, not a backup write.
3. **Fallback**: If auth fails, read `file_cache` from the local state file. The cache contains per-file `mime`, `type` (text/binary), and `size` (bytes) fields written by this version of the tool. State files created before this release (which did not store `size`) will have entries where `size` is absent — in this case `sizes_available` is set to `False`. If no state file exists and auth also fails, print `"Cannot enumerate files: auth failed and no local state exists"` and exit 2.
4. Classify each file by MIME type only (no downloads).
5. Sum file counts and sizes per group (text / binary).
6. Print a formatted report and exit 0. No backup files are written, no git commits made, no backup state file updated.

### Error types

```python
class DryRunSource(Enum):
    DRIVE_API = "drive_api"
    LOCAL_STATE = "local_state"
```

### New types in `sync_engine.py`

```python
@dataclass
class DryRunReport:
    source: DryRunSource
    text_file_count: int
    binary_file_count: int
    text_size_bytes: int
    binary_size_bytes: int
    sizes_available: bool       # False when state cache lacks size fields (pre-release state file)
    # Config display fields (extracted from Config in cli.py, not the full Config object):
    git_repo_path: str
    mirror_path: str
    auth_method: str            # always read from config — available even when auth failed
    include_shared: bool
    max_file_size_mb: int
    github_repo: Optional[str]  # "{owner}/{repo}" from config — not checked against GitHub API
```

`SyncEngine` gains a `run_dry() -> DryRunReport` method. It reuses `drive_client.list_all_files()` but skips all download and write calls. Config display fields are extracted in `cli.py` and passed in.

### CLI output (example)

```
Dry run — no files will be written

Source:         drive_api
Text files:     1,234  (2.3 GB)
Binary files:     456  (8.7 GB)
Total:          1,690  (11.0 GB)

Git repo:       ~/gdrive-backup-repo
Mirror:         ~/gdrive-backup-mirror
GitHub repo:    eyal050/gdrive-backup-data
Auth method:    oauth
Include shared: false
Max file size:  100 MB
```

If `sizes_available` is False, size columns show `(size unknown)`. The `github_repo` line shows `(not validated — value from config)` to clarify it has not been checked against the GitHub API.

---

## 2. GitHub Connector

### Error types

```python
class GithubError(Exception):
    def __init__(self, message: str, status_code: Optional[int] = None): ...
```

`GithubError` is caught in `cli.py`, always logged at ERROR level, and results in exit 2.

### New module: `github_manager.py`

```python
class GithubManager:
    def __init__(self, pat: str, owner: str, repo: str, private: bool, auto_create: bool): ...

    def validate_pat(self) -> None:
        """GET /user. Raises GithubError if PAT is invalid or lacks required scope."""

    def ensure_repo_exists(self) -> None:
        """
        GET /repos/{owner}/{repo}.
        - 200: proceed.
        - 404 + auto_create=True: create repo (POST /user/repos or /orgs/{owner}/repos).
        - 404 + auto_create=False: raise GithubError("Repo not found and auto_create is disabled").
        - 403: raise GithubError("Access denied — check PAT scope (requires 'repo')").
        - Other non-2xx: raise GithubError with status code.
        """

    def ensure_branch_exists(self, branch: str, base_branch: str = "main") -> None:
        """
        Create `branch` on the configured repo branching from `base_branch` if absent.
        In e2e new_branch mode: branch = timestamped name, base_branch = "main".
        Raises GithubError on API failure.
        """

    def get_authenticated_remote_url(self) -> str:
        """Returns https://x-access-token:{pat}@github.com/{owner}/{repo}.git"""
```

**PAT resolution order:**
1. `GITHUB_PAT` environment variable
2. `github.pat` config value

If neither is set and `github.enabled` is true, the run aborts with exit 2 and a clear error message. The PAT must **never** be passed as a CLI argument — it must always come via the environment variable or config file.

**PAT security:**
- PAT must never appear in log output. All log statements use `owner/repo`, not the remote URL.
- `e2e_config*.yaml` added to `.gitignore` to prevent accidental commit.
- After push (success or failure), the authenticated remote URL is replaced with the public URL `https://github.com/{owner}/{repo}.git` to strip the PAT from the backup repo's `.git/config`. Exceptions raised during this cleanup step are suppressed (logged at DEBUG level) so they do not mask a `GitError` from the push itself.

### Extensions to `GitManager`

```python
def set_remote(self, name: str, url: str) -> None:
    """Add remote if absent; update URL if changed."""

def remove_remote(self, name: str) -> None:
    """Remove remote if it exists; no-op if absent (never raises)."""

def push(self, remote: str = "origin", branch: str = "main") -> None:
    """Push current branch to remote. Raises GitError on failure."""
```

`remove_remote` is always safe to call — if the remote was never added (e.g., `set_remote` failed), it silently does nothing.

### Config changes

New optional top-level section in `config.yaml`:

```yaml
github:
  enabled: true
  pat: ""              # leave blank to use GITHUB_PAT env var; never logged
  owner: "eyal050"
  repo: "gdrive-backup-data"
  private: true
  auto_create: true
  e2e:                 # optional; absent in normal production configs
    output_mode: new_repo    # "new_repo" or "new_branch"; validated at config-load time
    base_repo: "gdrive-backup-data"  # required when output_mode is new_branch
```

At config-load time: if `e2e.output_mode` is present but not exactly `"new_repo"` or `"new_branch"` (case-sensitive), raise `ConfigError`. If `e2e.output_mode` is `"new_branch"` and `e2e.base_repo` is absent or empty, also raise `ConfigError`.

```python
@dataclass
class GithubConfig:
    enabled: bool
    pat: str
    owner: str
    repo: str
    private: bool
    auto_create: bool
    e2e_output_mode: Optional[str]   # None | "new_repo" | "new_branch"
    e2e_base_repo: Optional[str]
```

### `init` additions

After existing setup prompts, a new optional block:

```
Enable GitHub push? [y/N]
  GitHub owner (user or org): eyal050
  Repository name: gdrive-backup-data
  Private repo? [Y/n]
  Auto-create if missing? [Y/n]
  GitHub PAT (leave blank to use GITHUB_PAT env var): [masked via getpass]
```

If a PAT is provided, `validate_pat()` is called immediately. On failure, the user is warned and asked to confirm before saving.

### Run flow

In `cli.py` `run` command, after `engine.run()`. The entire GitHub block is **skipped when `--dry-run` is active**:

```python
if not dry_run and config.github and config.github.enabled:
    pat = resolve_pat(config)   # aborts with exit 2 if missing
    # "e2e mode" = config.github.e2e_output_mode is not None
    repo_name = resolve_repo_name(config)   # timestamped name if e2e mode, else config.github.repo
    # In new_branch mode: push local "main" → remote branch named repo_name (the timestamp).
    # In new_repo mode:   push local "main" → remote "main".
    remote_branch = repo_name if config.github.e2e_output_mode == "new_branch" else "main"
    mgr = GithubManager(pat, config.github.owner, repo_name, ...)
    try:
        mgr.validate_pat()
        if config.github.e2e_output_mode == "new_branch":
            mgr.ensure_branch_exists(branch=repo_name, base_branch="main")
        else:
            mgr.ensure_repo_exists()
        url = mgr.get_authenticated_remote_url()
        try:
            # set_remote is inside try so the finally's remove_remote always covers it,
            # even if set_remote itself fails.
            engine.git_manager.set_remote("origin", url)
            engine.git_manager.push(remote="origin", branch=remote_branch)
        except GitError as e:
            logger.error(f"GitHub push failed: {e}")
        finally:
            engine.git_manager.remove_remote("origin")   # no-op if set_remote failed
    except GithubError as e:
        logger.error(f"GitHub error: {e}")
        sys.exit(2)
```

Push failure is non-fatal: exit 0 if `stats.failed == 0`. Pre-push `GithubError` (validate/create) is fatal: exit 2.

**`push(remote, branch)` semantics:** pushes the currently checked-out local branch to `remote/branch` (i.e., `HEAD:refs/heads/{branch}`).

### E2E naming

`resolve_repo_name()` returns `DD-MM-YYYY-HH-MM_gdrive-backup` using `datetime.now(timezone.utc)` when `config.github.e2e_output_mode is not None`.

---

## 3. CI/CD Pipelines

### `ci.yml`

**Triggers:** push and pull_request to `main`
**Matrix:** Python 3.10, 3.11, 3.12
**Steps:**
1. `actions/checkout@v4`
2. `actions/setup-python@v4` with matrix version
3. Configure git identity: `git config --global user.email "ci@gdrive-backup"` and `git config --global user.name "CI"`  (required for `GitManager` commits in `tests/test_e2e.py`)
4. `pip install -e ".[dev]"`
5. `pytest --cov=gdrive_backup --cov-report=xml`
6. Upload coverage artifact

Mock-based `tests/test_e2e.py` runs in this job. `git` is pre-installed on `ubuntu-latest`.

### `e2e.yml`

**Triggers:** `workflow_dispatch` with input:
```yaml
inputs:
  output_mode:
    description: "new_repo or new_branch"
    required: true
    default: new_repo
    type: choice
    options: [new_repo, new_branch]
```

**Required secrets:**

| Secret | Contents |
|---|---|
| `GDRIVE_CREDENTIALS_JSON` | base64-encoded `credentials.json` |
| `GDRIVE_TOKEN_JSON` | base64-encoded `token.json` (pre-authorised) |
| `GITHUB_PAT_E2E` | PAT with `repo` + `delete_repo` scopes |
| `E2E_CONFIG_TEMPLATE` | base64-encoded config template (see below) |

**Config template** (stored as secret, never committed to repo):

```yaml
auth:
  method: oauth
  credentials_file: /tmp/gdrive_credentials.json
  token_file: /tmp/gdrive_token.json
backup:
  git_repo_path: /tmp/e2e-gdrive-repo
  mirror_path: /tmp/e2e-gdrive-mirror
scope:
  include_shared: false
  folder_ids: []
sync:
  state_file: /tmp/e2e-state.json
max_file_size_mb: 10
logging:
  max_size_mb: 10
  max_files: 3
  default_level: info
daemon:
  poll_interval: 300
github:
  enabled: true
  pat: ""           # PAT injected via GITHUB_PAT env var at runtime — never hardcoded here
  owner: "eyal050"
  repo: "gdrive-backup-data"
  private: true
  auto_create: true
  e2e:
    output_mode: "__OUTPUT_MODE__"   # placeholder substituted by workflow step
    base_repo: "gdrive-backup-data"
```

**Workflow steps:**
1. `actions/checkout@v4` + `actions/setup-python@v4` (Python 3.11)
2. Configure git identity (same as ci.yml step 3)
3. `pip install -e ".[dev]"`
4. Decode `GDRIVE_CREDENTIALS_JSON` → `/tmp/gdrive_credentials.json`
5. Decode `GDRIVE_TOKEN_JSON` → `/tmp/gdrive_token.json`
6. Decode `E2E_CONFIG_TEMPLATE` → `/tmp/e2e_config.yaml`; substitute `__OUTPUT_MODE__`. If substitution fails (placeholder absent), the step fails immediately with an explicit error before the tool is invoked.
7. `GITHUB_PAT=${{ secrets.GITHUB_PAT_E2E }} gdrive-backup run --config /tmp/e2e_config.yaml`  (PAT via env var only — never as a CLI argument)
8. Print summary: git log of backup repo, mirror file listing, GitHub repo/branch URL
9. **Post-step (`if: always()`)**: `python scripts/cleanup_e2e.py --delete --yes --mode ${{ inputs.output_mode }} --pat ${{ secrets.GITHUB_PAT_E2E }} --owner eyal050`

**Token expiry**: If `GDRIVE_TOKEN_JSON` expires, the run fails with `AuthError`. Refresh by re-running `gdrive-backup init` locally, then update the `GDRIVE_TOKEN_JSON` secret.

### Mock-based `tests/test_e2e.py`

Wires `SyncEngine` with a mock `DriveClient` returning a fixed set of fake text and binary files. Uses real `GitManager` and `MirrorManager` in pytest's `tmp_path`.

Asserts:
- Text files landed in git repo with a commit
- Binary files landed in mirror directory
- State file written with correct structure
- Incremental run (simulated change in mock) produces correct delta

`GithubManager` is excluded; covered by `tests/test_github_manager.py` with mocked `requests`.

---

## 4. Cleanup Script (`scripts/cleanup_e2e.py`)

Standalone Python script using `requests` (project dependency).

```
python scripts/cleanup_e2e.py
    [--delete] [--yes]
    [--mode new_repo|new_branch]
    [--base-repo OWNER/REPO]
    [--repo-dir PATH] [--mirror-dir PATH]
    [--pat TOKEN] [--owner OWNER]
```

| Flag | Behaviour |
|---|---|
| *(no flags)* | List matched repos/branches only — no changes made |
| `--delete` | Delete matched repos or branches on GitHub |
| `--yes` | Skip confirmation (for CI); without it, prompts `Delete the above? [y/N]` |
| `--mode` | `new_repo` (default): match/delete repos; `new_branch`: match/delete branches on `--base-repo` |
| `--base-repo OWNER/REPO` | Required with `--mode new_branch`; exits with error if omitted |
| `--repo-dir PATH` | Delete local git repo directory at PATH |
| `--mirror-dir PATH` | Delete local mirror directory at PATH |
| `--pat TOKEN` | Override PAT. **For interactive use, prefer the `GITHUB_PAT` env var** to avoid PAT appearing in shell history. `--pat` is intended for CI use only. |
| `--owner OWNER` | GitHub owner (default: `GITHUB_OWNER` env var, then interactive prompt) |

**Pattern:** `\d{2}-\d{2}-\d{4}-\d{2}-\d{2}_gdrive-backup`

**Pagination:** follows `Link: <...>; rel="next"` headers until all pages are fetched.

**Exit codes:** 0 on success, 1 on error (missing required flag, API failure), 2 if `--base-repo` is missing with `--mode new_branch`.

---

## New Dependency

`requests>=2.31` added to `pyproject.toml` (used by `github_manager.py` and `scripts/cleanup_e2e.py`).

---

## `.gitignore` additions

```
e2e_config*.yaml
```

---

## File Changes Summary

| File | Change |
|---|---|
| `src/gdrive_backup/github_manager.py` | **New** — `GithubManager`, `GithubError` |
| `src/gdrive_backup/sync_engine.py` | Add `DryRunSource`, `DryRunReport`, `run_dry()` |
| `src/gdrive_backup/git_manager.py` | Add `set_remote()`, `remove_remote()`, `push()` |
| `src/gdrive_backup/config.py` | Add `GithubConfig`, `github` field on `Config`; validate `e2e.output_mode` |
| `src/gdrive_backup/cli.py` | `--dry-run` on `run`; GitHub prompts in `init`; push after `engine.run()` |
| `config.example.yaml` | Add `github` section |
| `pyproject.toml` | Add `requests>=2.31`; confirm `requires-python = ">=3.10"` |
| `.gitignore` | Add `e2e_config*.yaml` |
| `tests/test_github_manager.py` | **New** |
| `tests/test_e2e.py` | **New** (mock-based) |
| `.github/workflows/ci.yml` | **New** |
| `.github/workflows/e2e.yml` | **New** |
| `scripts/cleanup_e2e.py` | **New** |
