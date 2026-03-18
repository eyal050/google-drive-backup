# Dry Run, GitHub Connector, and CI/CD Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add dry-run preview mode, GitHub push integration, CI/CD pipelines, and an e2e cleanup script to `gdrive-backup`.

**Architecture:** New `github_manager.py` owns all GitHub API calls; `git_manager.py` gains push support; `sync_engine.py` gains a read-only `run_dry()` path; `cli.py` wires everything together. Two GitHub Actions workflows cover unit tests (every push) and real end-to-end backup (manual dispatch).

**Tech Stack:** Python 3.10+, `requests>=2.31`, `gitpython>=3.1`, `click>=8.1`, GitHub REST API v3, GitHub Actions.

---

## File Map

| File | Action | Responsibility |
|---|---|---|
| `pyproject.toml` | Modify | Add `requests>=2.31` dependency |
| `.gitignore` | Modify | Add `e2e_config*.yaml` |
| `src/gdrive_backup/config.py` | Modify | Add `GithubConfig` dataclass + parsing |
| `src/gdrive_backup/github_manager.py` | Create | `GithubError`, `GithubManager` class |
| `src/gdrive_backup/git_manager.py` | Modify | Add `set_remote()`, `remove_remote()`, `push()` |
| `src/gdrive_backup/sync_engine.py` | Modify | Add `DryRunSource`, `DryRunReport`, `run_dry()` |
| `src/gdrive_backup/cli.py` | Modify | `--dry-run` flag; GitHub `init` prompts; post-run push |
| `config.example.yaml` | Modify | Add `github` section |
| `tests/test_config.py` | Modify | Tests for `GithubConfig` parsing + validation |
| `tests/test_github_manager.py` | Create | Unit tests for `GithubManager` (mocked `requests`) |
| `tests/test_git_manager.py` | Modify | Tests for `set_remote`, `remove_remote`, `push` |
| `tests/test_sync_engine.py` | Modify | Tests for `run_dry()` |
| `tests/test_cli.py` | Modify | Tests for `--dry-run` flag and GitHub `init` prompts |
| `tests/test_e2e.py` | Create | Mock-based end-to-end full scan + incremental |
| `.github/workflows/ci.yml` | Create | Unit test CI matrix |
| `.github/workflows/e2e.yml` | Create | Real backup workflow (manual dispatch) |
| `scripts/cleanup_e2e.py` | Create | Delete e2e repos/branches + local dirs |

---

## Task 1: Add `requests` dependency and `.gitignore` entry

**Files:**
- Modify: `pyproject.toml`
- Modify: `.gitignore`

- [ ] **Step 1: Add `requests>=2.31` to `pyproject.toml`**

In the `dependencies` list:
```toml
dependencies = [
    "click>=8.1",
    "google-api-python-client>=2.100",
    "google-auth>=2.23",
    "google-auth-oauthlib>=1.1",
    "gitpython>=3.1",
    "python-magic>=0.4",
    "pyyaml>=6.0",
    "requests>=2.31",
]
```

- [ ] **Step 2: Add `.gitignore` entry**

Append to `.gitignore`:
```
e2e_config*.yaml
```

- [ ] **Step 3: Reinstall and verify**

```bash
pip install -e ".[dev]"
python -c "import requests; print(requests.__version__)"
```
Expected: a version string like `2.31.0` or higher.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .gitignore
git commit -m "chore: add requests dependency and e2e gitignore entry"
```

---

## Task 2: `GithubConfig` in `config.py`

**Files:**
- Modify: `src/gdrive_backup/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_config.py`:

```python
def test_github_config_parsed(tmp_path):
    """GithubConfig is parsed from the github section."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
auth:
  method: oauth
  credentials_file: creds.json
  token_file: token.json
backup:
  git_repo_path: /tmp/repo
  mirror_path: /tmp/mirror
github:
  enabled: true
  pat: "mytoken"
  owner: "alice"
  repo: "backup-data"
  private: true
  auto_create: true
""")
    cfg_file.chmod(0o600)
    config = load_config(str(cfg_file), str(tmp_path))
    assert config.github is not None
    assert config.github.enabled is True
    assert config.github.pat == "mytoken"
    assert config.github.owner == "alice"
    assert config.github.repo == "backup-data"
    assert config.github.private is True
    assert config.github.auto_create is True
    assert config.github.e2e_output_mode is None
    assert config.github.e2e_base_repo is None


def test_github_config_absent(tmp_path):
    """Config without github section has github=None."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
auth:
  method: oauth
  credentials_file: creds.json
  token_file: token.json
backup:
  git_repo_path: /tmp/repo
  mirror_path: /tmp/mirror
""")
    cfg_file.chmod(0o600)
    config = load_config(str(cfg_file), str(tmp_path))
    assert config.github is None


def test_github_config_e2e_new_repo(tmp_path):
    """e2e.output_mode new_repo is accepted."""
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
auth:
  method: oauth
  credentials_file: creds.json
  token_file: token.json
backup:
  git_repo_path: /tmp/repo
  mirror_path: /tmp/mirror
github:
  enabled: true
  pat: ""
  owner: "alice"
  repo: "backup-data"
  private: true
  auto_create: true
  e2e:
    output_mode: new_repo
""")
    cfg_file.chmod(0o600)
    config = load_config(str(cfg_file), str(tmp_path))
    assert config.github.e2e_output_mode == "new_repo"


def test_github_config_e2e_invalid_mode(tmp_path):
    """Invalid e2e.output_mode raises ConfigError."""
    from gdrive_backup.config import ConfigError
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
auth:
  method: oauth
  credentials_file: creds.json
  token_file: token.json
backup:
  git_repo_path: /tmp/repo
  mirror_path: /tmp/mirror
github:
  enabled: true
  pat: ""
  owner: "alice"
  repo: "backup-data"
  private: true
  auto_create: false
  e2e:
    output_mode: bad_value
""")
    cfg_file.chmod(0o600)
    with pytest.raises(ConfigError, match="e2e.output_mode"):
        load_config(str(cfg_file), str(tmp_path))


def test_github_config_e2e_new_branch_requires_base_repo(tmp_path):
    """new_branch mode without base_repo raises ConfigError."""
    from gdrive_backup.config import ConfigError
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("""
auth:
  method: oauth
  credentials_file: creds.json
  token_file: token.json
backup:
  git_repo_path: /tmp/repo
  mirror_path: /tmp/mirror
github:
  enabled: true
  pat: ""
  owner: "alice"
  repo: "backup-data"
  private: true
  auto_create: false
  e2e:
    output_mode: new_branch
""")
    cfg_file.chmod(0o600)
    with pytest.raises(ConfigError, match="base_repo"):
        load_config(str(cfg_file), str(tmp_path))
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py::test_github_config_parsed tests/test_config.py::test_github_config_absent -v
```
Expected: FAIL (`Config` has no `github` attribute).

- [ ] **Step 3: Implement `GithubConfig` in `config.py`**

Add after the existing imports:

```python
VALID_E2E_OUTPUT_MODES = ("new_repo", "new_branch")


@dataclass
class GithubConfig:
    """GitHub push configuration."""
    enabled: bool
    pat: str
    owner: str
    repo: str
    private: bool
    auto_create: bool
    e2e_output_mode: Optional[str]   # None | "new_repo" | "new_branch"
    e2e_base_repo: Optional[str]
```

Add `github: Optional["GithubConfig"] = None` to the `Config` dataclass (add `field(default=None)` or just use `Optional` with default). Since `Config` is a plain dataclass, fields with defaults must come after fields without, so add it at the end:

```python
# in Config dataclass, add at the end:
github: Optional[GithubConfig] = None
```

Add a parsing helper and call it from `_validate_and_resolve`:

```python
def _parse_github_config(raw: dict) -> GithubConfig:
    """Parse and validate the github config section."""
    e2e_raw = raw.get("e2e") or {}
    e2e_output_mode = e2e_raw.get("output_mode") or None
    e2e_base_repo = e2e_raw.get("base_repo") or None

    if e2e_output_mode is not None and e2e_output_mode not in VALID_E2E_OUTPUT_MODES:
        raise ConfigError(
            f"Invalid github.e2e.output_mode: '{e2e_output_mode}'. "
            f"Must be one of {VALID_E2E_OUTPUT_MODES}"
        )
    if e2e_output_mode == "new_branch" and not e2e_base_repo:
        raise ConfigError(
            "github.e2e.base_repo is required when e2e.output_mode is 'new_branch'"
        )

    return GithubConfig(
        enabled=bool(raw.get("enabled", False)),
        pat=str(raw.get("pat", "") or ""),
        owner=str(raw.get("owner", "")),
        repo=str(raw.get("repo", "")),
        private=bool(raw.get("private", True)),
        auto_create=bool(raw.get("auto_create", True)),
        e2e_output_mode=e2e_output_mode,
        e2e_base_repo=e2e_base_repo,
    )
```

In `_validate_and_resolve`, after all existing parsing, add:

```python
    github_raw = raw.get("github")
    github_config = _parse_github_config(github_raw) if github_raw else None

    return Config(
        # ... existing fields ...,
        github=github_config,
    )
```

Also update the `Optional` import at the top of the file if not already present.

- [ ] **Step 4: Run all config tests**

```bash
pytest tests/test_config.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/config.py tests/test_config.py
git commit -m "feat: add GithubConfig to config with e2e validation"
```

---

## Task 3: `GithubManager` module

**Files:**
- Create: `src/gdrive_backup/github_manager.py`
- Create: `tests/test_github_manager.py`

- [ ] **Step 1: Write failing tests**

Create `tests/test_github_manager.py`:

```python
"""Unit tests for GithubManager — all HTTP calls are mocked."""
import pytest
from unittest.mock import MagicMock, patch, call
from gdrive_backup.github_manager import GithubManager, GithubError


@pytest.fixture
def mgr():
    return GithubManager(
        pat="test_pat",
        owner="alice",
        repo="backup",
        private=True,
        auto_create=True,
    )


def _mock_response(status_code, json_data=None):
    resp = MagicMock()
    resp.status_code = status_code
    resp.ok = 200 <= status_code < 300
    resp.json.return_value = json_data or {}
    return resp


class TestValidatePat:
    def test_valid_pat(self, mgr):
        with patch.object(mgr._session, "get", return_value=_mock_response(200)):
            mgr.validate_pat()  # should not raise

    def test_invalid_pat_raises(self, mgr):
        with patch.object(mgr._session, "get", return_value=_mock_response(401)):
            with pytest.raises(GithubError, match="Invalid PAT"):
                mgr.validate_pat()

    def test_server_error_raises(self, mgr):
        with patch.object(mgr._session, "get", return_value=_mock_response(500)):
            with pytest.raises(GithubError, match="500"):
                mgr.validate_pat()


class TestEnsureRepoExists:
    def test_repo_exists(self, mgr):
        with patch.object(mgr._session, "get", return_value=_mock_response(200)):
            mgr.ensure_repo_exists()  # should not raise

    def test_repo_not_found_auto_create(self, mgr):
        get_resp = _mock_response(404)
        create_resp = _mock_response(201)
        with patch.object(mgr._session, "get", return_value=get_resp), \
             patch.object(mgr._session, "post", return_value=create_resp):
            mgr.ensure_repo_exists()

    def test_repo_not_found_no_auto_create(self, mgr):
        mgr._auto_create = False
        with patch.object(mgr._session, "get", return_value=_mock_response(404)):
            with pytest.raises(GithubError, match="auto_create is disabled"):
                mgr.ensure_repo_exists()

    def test_access_denied_raises(self, mgr):
        with patch.object(mgr._session, "get", return_value=_mock_response(403)):
            with pytest.raises(GithubError, match="Access denied"):
                mgr.ensure_repo_exists()

    def test_unexpected_status_raises(self, mgr):
        with patch.object(mgr._session, "get", return_value=_mock_response(503)):
            with pytest.raises(GithubError, match="503"):
                mgr.ensure_repo_exists()


class TestEnsureBranchExists:
    def test_branch_created_when_absent(self, mgr):
        sha_resp = _mock_response(200, {"object": {"sha": "abc123"}})
        not_found = _mock_response(404)
        create_resp = _mock_response(201)
        get_calls = [sha_resp, not_found]
        with patch.object(mgr._session, "get", side_effect=get_calls), \
             patch.object(mgr._session, "post", return_value=create_resp):
            mgr.ensure_branch_exists("new-branch", "main")

    def test_branch_already_exists(self, mgr):
        sha_resp = _mock_response(200, {"object": {"sha": "abc123"}})
        exists_resp = _mock_response(200)
        with patch.object(mgr._session, "get", side_effect=[sha_resp, exists_resp]):
            mgr.ensure_branch_exists("existing-branch", "main")

    def test_base_branch_not_found_raises(self, mgr):
        with patch.object(mgr._session, "get", return_value=_mock_response(404)):
            with pytest.raises(GithubError, match="Base branch"):
                mgr.ensure_branch_exists("new", "nonexistent")


class TestGetAuthenticatedRemoteUrl:
    def test_url_format(self, mgr):
        url = mgr.get_authenticated_remote_url()
        assert url == "https://x-access-token:test_pat@github.com/alice/backup.git"

    def test_pat_not_in_repr(self, mgr):
        """PAT must not appear in string representation."""
        assert "test_pat" not in repr(mgr)

    def test_public_url(self, mgr):
        url = mgr.get_public_remote_url()
        assert url == "https://github.com/alice/backup.git"
        assert "test_pat" not in url
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_github_manager.py -v
```
Expected: FAIL (`ModuleNotFoundError: No module named 'gdrive_backup.github_manager'`).

- [ ] **Step 3: Create `github_manager.py`**

Create `src/gdrive_backup/github_manager.py`:

```python
# src/gdrive_backup/github_manager.py
"""GitHub API integration for pushing backup repos."""

import logging
from typing import Optional

import requests as req

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.github.com"


class GithubError(Exception):
    """Raised when a GitHub API call fails."""

    def __init__(self, message: str, status_code: Optional[int] = None):
        super().__init__(message)
        self.status_code = status_code


class GithubManager:
    """Manages GitHub repository operations via the REST API."""

    def __init__(
        self,
        pat: str,
        owner: str,
        repo: str,
        private: bool = True,
        auto_create: bool = True,
    ):
        self._owner = owner
        self._repo = repo
        self._private = private
        self._auto_create = auto_create
        self._session = req.Session()
        self._session.headers.update(
            {
                "Authorization": f"token {pat}",
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
        # Store PAT only for URL construction — never log it
        self.__pat = pat

    def __repr__(self) -> str:
        return f"GithubManager(owner={self._owner!r}, repo={self._repo!r})"

    def validate_pat(self) -> None:
        """Verify the PAT is valid by calling GET /user."""
        resp = self._session.get(f"{_BASE_URL}/user", timeout=10)
        if resp.status_code == 401:
            raise GithubError("Invalid PAT or insufficient scope", resp.status_code)
        if not resp.ok:
            raise GithubError(
                f"PAT validation failed (HTTP {resp.status_code})", resp.status_code
            )
        logger.debug(f"PAT validated for {self._owner}/{self._repo}")

    def ensure_repo_exists(self) -> None:
        """Create the repo if it does not exist and auto_create is enabled."""
        resp = self._session.get(
            f"{_BASE_URL}/repos/{self._owner}/{self._repo}", timeout=10
        )
        if resp.status_code == 200:
            logger.debug(f"Repo {self._owner}/{self._repo} exists")
            return
        if resp.status_code == 403:
            raise GithubError(
                "Access denied — check PAT scope (requires 'repo')", 403
            )
        if resp.status_code == 404:
            if not self._auto_create:
                raise GithubError(
                    f"Repo {self._owner}/{self._repo} not found and auto_create is disabled",
                    404,
                )
            self._create_repo()
            return
        raise GithubError(
            f"Unexpected response checking repo (HTTP {resp.status_code})",
            resp.status_code,
        )

    def _create_repo(self) -> None:
        payload = {
            "name": self._repo,
            "private": self._private,
            "auto_init": False,
        }
        # Try personal repo first; fall back to org repo on 422 (Unprocessable Entity)
        resp = self._session.post(f"{_BASE_URL}/user/repos", json=payload, timeout=10)
        if resp.status_code == 422:
            resp = self._session.post(
                f"{_BASE_URL}/orgs/{self._owner}/repos", json=payload, timeout=10
            )
        if not resp.ok:
            raise GithubError(
                f"Failed to create repo {self._owner}/{self._repo} "
                f"(HTTP {resp.status_code})",
                resp.status_code,
            )
        logger.info(f"Created repo {self._owner}/{self._repo}")

    def ensure_branch_exists(self, branch: str, base_branch: str = "main") -> None:
        """Create `branch` on the configured repo if it does not exist."""
        # Get SHA of base_branch
        ref_resp = self._session.get(
            f"{_BASE_URL}/repos/{self._owner}/{self._repo}/git/ref/heads/{base_branch}",
            timeout=10,
        )
        if not ref_resp.ok:
            raise GithubError(
                f"Base branch '{base_branch}' not found "
                f"(HTTP {ref_resp.status_code})",
                ref_resp.status_code,
            )
        sha = ref_resp.json()["object"]["sha"]

        # Check if target branch already exists
        check = self._session.get(
            f"{_BASE_URL}/repos/{self._owner}/{self._repo}/git/ref/heads/{branch}",
            timeout=10,
        )
        if check.status_code == 200:
            logger.debug(f"Branch '{branch}' already exists")
            return

        # Create branch
        create = self._session.post(
            f"{_BASE_URL}/repos/{self._owner}/{self._repo}/git/refs",
            json={"ref": f"refs/heads/{branch}", "sha": sha},
            timeout=10,
        )
        if not create.ok:
            raise GithubError(
                f"Failed to create branch '{branch}' (HTTP {create.status_code})",
                create.status_code,
            )
        logger.info(f"Created branch '{branch}' on {self._owner}/{self._repo}")

    def get_authenticated_remote_url(self) -> str:
        """Return a push URL with the PAT embedded."""
        return f"https://x-access-token:{self.__pat}@github.com/{self._owner}/{self._repo}.git"

    def get_public_remote_url(self) -> str:
        """Return the public (non-authenticated) remote URL."""
        return f"https://github.com/{self._owner}/{self._repo}.git"
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_github_manager.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/github_manager.py tests/test_github_manager.py
git commit -m "feat: add GithubManager with repo/branch creation and PAT validation"
```

---

## Task 4: `GitManager` — `set_remote`, `remove_remote`, `push`

**Files:**
- Modify: `src/gdrive_backup/git_manager.py`
- Modify: `tests/test_git_manager.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_git_manager.py` (look at existing test fixtures — there should be a `git_manager` fixture using `tmp_path`):

```python
def test_set_remote_adds_new(git_manager):
    git_manager.set_remote("origin", "https://github.com/alice/repo.git")
    assert "origin" in [r.name for r in git_manager._repo.remotes]
    assert git_manager._repo.remote("origin").url == "https://github.com/alice/repo.git"


def test_set_remote_updates_url(git_manager):
    git_manager.set_remote("origin", "https://github.com/alice/repo.git")
    git_manager.set_remote("origin", "https://github.com/alice/other.git")
    assert git_manager._repo.remote("origin").url == "https://github.com/alice/other.git"


def test_remove_remote_removes(git_manager):
    git_manager.set_remote("origin", "https://github.com/alice/repo.git")
    git_manager.remove_remote("origin")
    assert "origin" not in [r.name for r in git_manager._repo.remotes]


def test_remove_remote_noop_if_absent(git_manager):
    # Should not raise
    git_manager.remove_remote("nonexistent")


def test_push_raises_when_no_remote(git_manager):
    from gdrive_backup.git_manager import GitError
    with pytest.raises(GitError, match="not found"):
        git_manager.push(remote="origin", branch="main")
```

Note: a real push test requires a live remote — keep that out of unit tests. The failure mode (no remote) is sufficient to test the guard.

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_git_manager.py::test_set_remote_adds_new tests/test_git_manager.py::test_remove_remote_noop_if_absent -v
```
Expected: FAIL (`GitManager has no attribute 'set_remote'`).

- [ ] **Step 3: Implement the three methods in `git_manager.py`**

Add after the existing `commit()` method:

```python
def set_remote(self, name: str, url: str) -> None:
    """Add a remote or update its URL if it already exists."""
    try:
        remote = self._repo.remote(name)
        if remote.url != url:
            self._repo.delete_remote(remote)
            self._repo.create_remote(name, url)
            logger.debug(f"Updated remote '{name}' URL")
        else:
            logger.debug(f"Remote '{name}' URL unchanged")
    except ValueError:
        self._repo.create_remote(name, url)
        logger.debug(f"Added remote '{name}'")

def remove_remote(self, name: str) -> None:
    """Remove a remote if it exists; silently does nothing if absent."""
    try:
        remote = self._repo.remote(name)
        self._repo.delete_remote(remote)
        logger.debug(f"Removed remote '{name}'")
    except ValueError:
        pass  # already absent

def push(self, remote: str = "origin", branch: str = "main") -> None:
    """Push HEAD to remote/branch.

    Args:
        remote: Name of the git remote.
        branch: Remote branch name to push to (HEAD:refs/heads/{branch}).

    Raises:
        GitError: If the remote does not exist or push fails.
    """
    try:
        r = self._repo.remote(remote)
    except ValueError:
        raise GitError(f"Remote '{remote}' not found")

    refspec = f"HEAD:refs/heads/{branch}"
    try:
        push_infos = r.push(refspec=refspec)
    except Exception as e:
        raise GitError(f"Push to '{remote}/{branch}' failed: {e}") from e

    for info in push_infos:
        if info.flags & info.ERROR:
            raise GitError(f"Push to '{remote}/{branch}' failed: {info.summary}")

    logger.info(f"Pushed HEAD to {remote}/{branch}")
```

- [ ] **Step 4: Run git manager tests**

```bash
pytest tests/test_git_manager.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/git_manager.py tests/test_git_manager.py
git commit -m "feat: add set_remote, remove_remote, push to GitManager"
```

---

## Task 5: `SyncEngine.run_dry()`

**Files:**
- Modify: `src/gdrive_backup/sync_engine.py`
- Modify: `tests/test_sync_engine.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_sync_engine.py` (look at existing fixtures for `sync_engine` — it uses mock `DriveClient`):

```python
from gdrive_backup.sync_engine import DryRunSource, DryRunReport


def test_run_dry_drive_api(sync_engine, mock_drive_client):
    """run_dry() uses Drive API when available."""
    from gdrive_backup.drive_client import DriveFile
    mock_drive_client.list_all_files.return_value = [
        DriveFile(id="1", name="notes.txt", mime_type="text/plain",
                  size=1000, md5=None, modified_time=None, parents=[], should_skip=False,
                  is_exportable=False, export_mime_type=None, export_extension=None),
        DriveFile(id="2", name="photo.jpg", mime_type="image/jpeg",
                  size=5000, md5=None, modified_time=None, parents=[], should_skip=False,
                  is_exportable=False, export_mime_type=None, export_extension=None),
    ]
    report = sync_engine.run_dry(
        git_repo_path="/tmp/repo",
        mirror_path="/tmp/mirror",
        auth_method="oauth",
        max_file_size_mb=0,
        github_repo="alice/backup",
    )
    assert report.source == DryRunSource.DRIVE_API
    assert report.text_file_count == 1
    assert report.binary_file_count == 1
    assert report.text_size_bytes == 1000
    assert report.binary_size_bytes == 5000
    assert report.sizes_available is True
    assert report.github_repo == "alice/backup"


def test_run_dry_fallback_to_state(sync_engine, mock_drive_client, tmp_path):
    """run_dry() falls back to state file when Drive API fails."""
    mock_drive_client.list_all_files.side_effect = Exception("auth failed")

    # Pre-populate state file with a cache entry
    import json
    state = {
        "file_cache": {
            "f1": {"type": "text", "mime": "text/plain", "size": 2000, "local_path": "a.txt"},
            "f2": {"type": "binary", "mime": "image/jpeg", "size": 8000, "local_path": "b.jpg"},
        }
    }
    sync_engine._state_file.write_text(json.dumps(state))

    report = sync_engine.run_dry(
        git_repo_path="/tmp/repo",
        mirror_path="/tmp/mirror",
        auth_method="oauth",
        max_file_size_mb=0,
    )
    assert report.source == DryRunSource.LOCAL_STATE
    assert report.text_file_count == 1
    assert report.binary_file_count == 1
    assert report.text_size_bytes == 2000


def test_run_dry_no_state_no_auth_raises(sync_engine, mock_drive_client):
    """run_dry() raises SyncError when both API and state are unavailable."""
    from gdrive_backup.sync_engine import SyncError
    mock_drive_client.list_all_files.side_effect = Exception("auth failed")
    with pytest.raises(SyncError, match="no local state exists"):
        sync_engine.run_dry(
            git_repo_path="/tmp/repo",
            mirror_path="/tmp/mirror",
            auth_method="oauth",
            max_file_size_mb=0,
        )


def test_run_dry_sizes_unavailable_for_old_state(sync_engine, mock_drive_client, tmp_path):
    """sizes_available=False when state cache lacks size field."""
    mock_drive_client.list_all_files.side_effect = Exception("auth failed")
    import json
    state = {
        "file_cache": {
            "f1": {"type": "text", "mime": "text/plain", "local_path": "a.txt"},  # no size
        }
    }
    sync_engine._state_file.write_text(json.dumps(state))
    report = sync_engine.run_dry(
        git_repo_path="/tmp/repo",
        mirror_path="/tmp/mirror",
        auth_method="oauth",
        max_file_size_mb=0,
    )
    assert report.sizes_available is False
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_sync_engine.py::test_run_dry_drive_api -v
```
Expected: FAIL (`SyncEngine has no attribute 'run_dry'`).

- [ ] **Step 3: Implement `DryRunSource`, `DryRunReport`, `run_dry()` in `sync_engine.py`**

Add after the `SyncError` class:

```python
from enum import Enum


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
```

Add this method to `SyncEngine`:

```python
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
        for drive_file in self._drive.list_all_files(
            include_shared=self._include_shared,
            folder_ids=self._folder_ids if self._folder_ids else None,
        ):
            if drive_file.should_skip:
                continue
            file_type = self._classifier.classify_by_mime(drive_file.mime_type)
            size = drive_file.size or 0
            if file_type == FileType.TEXT:
                text_count += 1
                text_bytes += size
            else:
                binary_count += 1
                binary_bytes += size
    except Exception as e:
        logger.warning(f"Drive API unavailable for dry run, falling back to state: {e}")
        source = DryRunSource.LOCAL_STATE
        if not self._file_cache:
            raise SyncError(
                "Cannot enumerate files: auth failed and no local state exists"
            )
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
```

Also update `_process_file` to store `size` in the cache (required for fallback dry run to have sizes):

```python
# In _process_file, update the cache entry:
self._file_cache[drive_file.id] = {
    "type": file_type.value,
    "mime": drive_file.mime_type,
    "local_path": local_path,
    "md5": drive_file.md5,
    "last_modified": drive_file.modified_time,
    "size": drive_file.size,   # NEW — for dry run fallback
}
```

- [ ] **Step 4: Run sync engine tests**

```bash
pytest tests/test_sync_engine.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/sync_engine.py tests/test_sync_engine.py
git commit -m "feat: add run_dry() with DryRunSource/DryRunReport to SyncEngine"
```

---

## Task 6: CLI — `--dry-run` flag on `run` command

**Files:**
- Modify: `src/gdrive_backup/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:

```python
from click.testing import CliRunner
from unittest.mock import MagicMock, patch
from gdrive_backup.cli import main
from gdrive_backup.sync_engine import DryRunSource, DryRunReport


def _make_dry_run_report():
    return DryRunReport(
        source=DryRunSource.DRIVE_API,
        text_file_count=10,
        binary_file_count=5,
        text_size_bytes=1024 * 1024 * 100,  # 100 MB
        binary_size_bytes=1024 * 1024 * 500,  # 500 MB
        sizes_available=True,
        git_repo_path="/tmp/repo",
        mirror_path="/tmp/mirror",
        auth_method="oauth",
        include_shared=False,
        max_file_size_mb=0,
        github_repo="alice/backup",
    )


def test_dry_run_flag_calls_run_dry(tmp_path, fake_config_file):
    """--dry-run calls engine.run_dry() and prints report."""
    runner = CliRunner()
    report = _make_dry_run_report()
    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine:
        mock_cfg.return_value = MagicMock(
            github=None, log_dir=tmp_path, log_max_size_mb=10,
            log_max_files=5, log_default_level="info",
        )
        engine = MagicMock()
        engine.run_dry.return_value = report
        mock_engine.return_value = engine
        result = runner.invoke(main, ["run", "--dry-run", "--config", str(fake_config_file)])
    assert result.exit_code == 0
    engine.run_dry.assert_called_once()
    engine.run.assert_not_called()
    assert "Dry run" in result.output
    assert "Text files" in result.output
    assert "10" in result.output


def test_dry_run_skips_github_push(tmp_path, fake_config_file):
    """--dry-run never pushes to GitHub even if github.enabled."""
    runner = CliRunner()
    report = _make_dry_run_report()
    github_cfg = MagicMock(enabled=True, pat="tok", owner="alice", repo="backup",
                           e2e_output_mode=None)
    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine, \
         patch("gdrive_backup.cli.GithubManager") as mock_gh:
        mock_cfg.return_value = MagicMock(
            github=github_cfg, log_dir=tmp_path,
            log_max_size_mb=10, log_max_files=5, log_default_level="info",
        )
        engine = MagicMock()
        engine.run_dry.return_value = report
        mock_engine.return_value = engine
        result = runner.invoke(main, ["run", "--dry-run", "--config", str(fake_config_file)])
    assert result.exit_code == 0
    mock_gh.assert_not_called()


def test_dry_run_sizes_unknown_shows_message(tmp_path, fake_config_file):
    """When sizes_available=False, output includes 'size unknown'."""
    runner = CliRunner()
    report = _make_dry_run_report()
    report.sizes_available = False
    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine:
        mock_cfg.return_value = MagicMock(
            github=None, log_dir=tmp_path, log_max_size_mb=10,
            log_max_files=5, log_default_level="info",
        )
        engine = MagicMock()
        engine.run_dry.return_value = report
        mock_engine.return_value = engine
        result = runner.invoke(main, ["run", "--dry-run", "--config", str(fake_config_file)])
    assert "size unknown" in result.output
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_cli.py::test_dry_run_flag_calls_run_dry -v
```
Expected: FAIL.

- [ ] **Step 3: Add `--dry-run` to `run` command in `cli.py`**

Add the import at the top:
```python
from gdrive_backup.sync_engine import DryRunReport, DryRunSource
```

Add the flag to `run`:
```python
@main.command()
@click.option("--config", "config_path", default=None, help="Config file path")
@click.option("-v", "--verbose", is_flag=True)
@click.option("--debug", is_flag=True)
@click.option("-q", "--quiet", is_flag=True)
@click.option("-n", "--dry-run", "dry_run", is_flag=True,
              help="Preview what would be backed up without writing anything")
@click.pass_context
def run(ctx, config_path, verbose, debug, quiet, dry_run):
```

Add dry run branch at the start of the try block in `run`:

```python
    try:
        engine = _build_engine(config)
        if dry_run:
            github_repo = (
                f"{config.github.owner}/{config.github.repo}"
                if config.github and config.github.enabled
                else None
            )
            report = engine.run_dry(
                git_repo_path=str(config.git_repo_path),
                mirror_path=str(config.mirror_path),
                auth_method=config.auth_method,
                max_file_size_mb=config.max_file_size_mb,
                github_repo=github_repo,
            )
            _print_dry_run_report(report)
            return
        stats = engine.run()
        # ... existing GitHub push block and exit code logic ...
```

Add the report formatter:

```python
def _format_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"


def _print_dry_run_report(report: DryRunReport) -> None:
    size_str = "(size unknown)" if not report.sizes_available else None

    click.echo("Dry run — no files will be written\n")
    click.echo(f"Source:         {report.source.value}")
    text_size = size_str or _format_bytes(report.text_size_bytes)
    bin_size = size_str or _format_bytes(report.binary_size_bytes)
    total_size = size_str or _format_bytes(report.text_size_bytes + report.binary_size_bytes)
    click.echo(f"Text files:     {report.text_file_count:,}  ({text_size})")
    click.echo(f"Binary files:   {report.binary_file_count:,}  ({bin_size})")
    click.echo(f"Total:          {report.text_file_count + report.binary_file_count:,}  ({total_size})")
    click.echo("")
    click.echo(f"Git repo:       {report.git_repo_path}")
    click.echo(f"Mirror:         {report.mirror_path}")
    if report.github_repo:
        click.echo(f"GitHub repo:    {report.github_repo}  (not validated — value from config)")
    click.echo(f"Auth method:    {report.auth_method}")
    click.echo(f"Include shared: {str(report.include_shared).lower()}")
    click.echo(f"Max file size:  {'no limit' if report.max_file_size_mb == 0 else str(report.max_file_size_mb) + ' MB'}")
```

- [ ] **Step 4: Run CLI tests**

```bash
pytest tests/test_cli.py -v
```
Expected: all pass.

- [ ] **Step 5: Smoke test**

```bash
gdrive-backup run --dry-run --help
```
Expected: `--dry-run` listed in options.

- [ ] **Step 6: Commit**

```bash
git add src/gdrive_backup/cli.py tests/test_cli.py
git commit -m "feat: add --dry-run flag to run command with formatted report"
```

---

## Task 7: CLI — GitHub `init` prompts

**Files:**
- Modify: `src/gdrive_backup/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:

```python
def test_init_github_prompts_saved_to_config(tmp_path):
    """GitHub prompts during init are written to config file."""
    runner = CliRunner()
    input_lines = "\n".join([
        "oauth",           # auth method
        "",                # credentials file (default)
        str(tmp_path / "repo"),   # git repo path
        str(tmp_path / "mirror"), # mirror path
        "y",               # enable github
        "alice",           # owner
        "my-backup",       # repo
        "y",               # private
        "y",               # auto_create
        "",                # PAT (blank = use env var)
    ])
    result = runner.invoke(
        main, ["init", "--config", str(tmp_path / "config.yaml")],
        input=input_lines,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    config_text = (tmp_path / "config.yaml").read_text()
    assert "github" in config_text
    assert "alice" in config_text
    assert "my-backup" in config_text


def test_init_github_skipped_when_declined(tmp_path):
    """Saying 'n' to GitHub skips the github section."""
    runner = CliRunner()
    input_lines = "\n".join([
        "oauth", "", str(tmp_path / "repo"), str(tmp_path / "mirror"), "n",
    ])
    result = runner.invoke(
        main, ["init", "--config", str(tmp_path / "config.yaml")],
        input=input_lines,
        catch_exceptions=False,
    )
    assert result.exit_code == 0
    config_text = (tmp_path / "config.yaml").read_text()
    assert "github" not in config_text
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_cli.py::test_init_github_prompts_saved_to_config -v
```
Expected: FAIL (no GitHub prompts in `init`).

- [ ] **Step 3: Add GitHub prompts to `init` in `cli.py`**

Add import at the top:
```python
import getpass
from gdrive_backup.github_manager import GithubManager, GithubError
```

In the `init` command, after the existing `config_data` dict is built but before `yaml.dump`, add:

```python
    # GitHub setup
    github_data = None
    if click.confirm("\nEnable GitHub push?", default=False):
        gh_owner = click.prompt("  GitHub owner (user or org)")
        gh_repo = click.prompt("  Repository name")
        gh_private = click.confirm("  Private repo?", default=True)
        gh_auto_create = click.confirm("  Auto-create if missing?", default=True)
        gh_pat = getpass.getpass("  GitHub PAT (leave blank to use GITHUB_PAT env var): ").strip()

        if gh_pat:
            try:
                mgr = GithubManager(gh_pat, gh_owner, gh_repo, gh_private, gh_auto_create)
                mgr.validate_pat()
                click.echo("  PAT validated successfully.")
            except GithubError as e:
                click.echo(f"  Warning: PAT validation failed: {e}")
                if not click.confirm("  Save anyway?", default=False):
                    gh_pat = ""

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
```

- [ ] **Step 4: Run tests**

```bash
pytest tests/test_cli.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/cli.py tests/test_cli.py
git commit -m "feat: add GitHub setup prompts to init command"
```

---

## Task 8: CLI — post-run GitHub push

**Files:**
- Modify: `src/gdrive_backup/cli.py`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_cli.py`:

```python
def test_run_pushes_to_github_when_enabled(tmp_path, fake_config_file):
    """After engine.run(), pushes to GitHub when github.enabled."""
    runner = CliRunner()
    from gdrive_backup.sync_engine import SyncStats
    github_cfg = MagicMock(
        enabled=True, owner="alice", repo="backup",
        e2e_output_mode=None, pat="", e2e_base_repo=None,
    )
    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine, \
         patch("gdrive_backup.cli.GithubManager") as mock_gh_cls, \
         patch("os.environ.get", return_value="test_pat"):
        cfg = MagicMock(
            github=github_cfg, log_dir=tmp_path,
            log_max_size_mb=10, log_max_files=5, log_default_level="info",
        )
        mock_cfg.return_value = cfg
        engine = MagicMock()
        engine.run.return_value = SyncStats(added=2)
        mock_engine.return_value = engine
        gh_instance = MagicMock()
        gh_instance.get_authenticated_remote_url.return_value = "https://x-access-token:test_pat@github.com/alice/backup.git"
        gh_instance.get_public_remote_url.return_value = "https://github.com/alice/backup.git"
        mock_gh_cls.return_value = gh_instance
        result = runner.invoke(main, ["run", "--config", str(fake_config_file)])
    assert result.exit_code == 0
    gh_instance.validate_pat.assert_called_once()
    gh_instance.ensure_repo_exists.assert_called_once()
    engine.git_manager.push.assert_called_once()
    engine.git_manager.remove_remote.assert_called_once_with("origin")


def test_run_github_push_failure_is_nonfatal(tmp_path, fake_config_file):
    """Push failure does not change exit code to non-zero."""
    from gdrive_backup.sync_engine import SyncStats
    from gdrive_backup.git_manager import GitError
    runner = CliRunner()
    github_cfg = MagicMock(enabled=True, owner="alice", repo="backup",
                           e2e_output_mode=None, pat="tok", e2e_base_repo=None)
    with patch("gdrive_backup.cli.load_config") as mock_cfg, \
         patch("gdrive_backup.cli._build_engine") as mock_engine, \
         patch("gdrive_backup.cli.GithubManager") as mock_gh_cls:
        mock_cfg.return_value = MagicMock(
            github=github_cfg, log_dir=tmp_path,
            log_max_size_mb=10, log_max_files=5, log_default_level="info",
        )
        engine = MagicMock()
        engine.run.return_value = SyncStats(added=1)
        engine.git_manager.push.side_effect = GitError("network error")
        mock_engine.return_value = engine
        gh_instance = MagicMock()
        gh_instance.get_authenticated_remote_url.return_value = "https://x-access-token:tok@github.com/alice/backup.git"
        mock_gh_cls.return_value = gh_instance
        result = runner.invoke(main, ["run", "--config", str(fake_config_file)])
    assert result.exit_code == 0  # non-fatal
    engine.git_manager.remove_remote.assert_called_once_with("origin")  # cleanup always runs
```

- [ ] **Step 2: Run to verify failure**

```bash
pytest tests/test_cli.py::test_run_pushes_to_github_when_enabled -v
```
Expected: FAIL.

- [ ] **Step 3: Add GitHub push block to `run` command in `cli.py`**

Add a helper for PAT and repo name resolution:

```python
import os
from datetime import datetime, timezone


def _resolve_pat(config) -> Optional[str]:
    """Resolve PAT from env var (priority) or config value."""
    return os.environ.get("GITHUB_PAT") or config.github.pat or None


def _resolve_repo_name(config) -> str:
    """Return timestamped name in e2e mode, else config.github.repo."""
    if config.github.e2e_output_mode is not None:
        return datetime.now(timezone.utc).strftime("%d-%m-%Y-%H-%M") + "_gdrive-backup"
    return config.github.repo
```

In the `run` command, after the existing `stats = engine.run()` line and before `sys.exit(...)`, add:

```python
        # GitHub push (skipped when --dry-run; dry_run branch already returned above)
        if config.github and config.github.enabled:
            pat = _resolve_pat(config)
            if not pat:
                click.echo("GitHub push skipped: no PAT found (set GITHUB_PAT or github.pat in config)", err=True)
                sys.exit(2)
            repo_name = _resolve_repo_name(config)
            remote_branch = repo_name if config.github.e2e_output_mode == "new_branch" else "main"
            try:
                from gdrive_backup.github_manager import GithubManager, GithubError
                mgr = GithubManager(
                    pat,
                    config.github.owner,
                    repo_name,
                    config.github.private,
                    config.github.auto_create,
                )
                mgr.validate_pat()
                if config.github.e2e_output_mode == "new_branch":
                    mgr.ensure_branch_exists(branch=repo_name, base_branch="main")
                else:
                    mgr.ensure_repo_exists()
                auth_url = mgr.get_authenticated_remote_url()
                pub_url = mgr.get_public_remote_url()
                try:
                    engine.git_manager.set_remote("origin", auth_url)
                    engine.git_manager.push(remote="origin", branch=remote_branch)
                    logger.info(f"Pushed to {config.github.owner}/{repo_name}")
                except GitError as push_err:
                    logger.error(f"GitHub push failed: {push_err}")
                finally:
                    engine.git_manager.remove_remote("origin")
            except GithubError as e:
                logger.error(f"GitHub error: {e}")
                sys.exit(2)
```

Note: `GithubManager` and `GithubError` are already imported at the top of `cli.py` from Task 7. `GitError` should be imported at the top alongside them: `from gdrive_backup.git_manager import GitError`. The test's `patch("gdrive_backup.cli.GithubManager")` relies on the top-level import.

- [ ] **Step 4: Run all CLI tests**

```bash
pytest tests/test_cli.py -v
```
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add src/gdrive_backup/cli.py tests/test_cli.py
git commit -m "feat: push to GitHub after backup run when github.enabled"
```

---

## Task 9: Mock-based end-to-end test (`tests/test_e2e.py`)

**Files:**
- Create: `tests/test_e2e.py`

- [ ] **Step 1: Create the test file**

```python
# tests/test_e2e.py
"""Mock-based end-to-end test: real SyncEngine + GitManager + MirrorManager,
mock DriveClient. No real Drive credentials needed."""

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from gdrive_backup.classifier import FileClassifier
from gdrive_backup.drive_client import DriveFile
from gdrive_backup.git_manager import GitManager
from gdrive_backup.mirror_manager import MirrorManager
from gdrive_backup.sync_engine import SyncEngine


def _make_drive_file(file_id, name, mime_type, size=100, content=b"hello"):
    f = MagicMock(spec=DriveFile)
    f.id = file_id
    f.name = name
    f.mime_type = mime_type
    f.size = size
    f.md5 = None
    f.modified_time = "2026-01-01T00:00:00Z"
    f.parents = []
    f.should_skip = False
    f.is_exportable = False
    f.export_mime_type = None
    f.export_extension = None
    return f


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

    # Text file in git repo
    git_files = list(s["git_path"].rglob("*.txt"))
    assert len(git_files) == 1
    assert git_files[0].read_bytes() == b"hello text"

    # Binary file in mirror
    mirror_files = list(s["mirror_path"].rglob("*.jpg"))
    assert len(mirror_files) == 1

    # State file written
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

    # First: full scan with one file
    s["mock_drive"].list_all_files.return_value = [s["text_file"]]
    s["mock_drive"].download_file.return_value = b"original"
    s["engine"].run_full_scan()

    # Second: incremental with a new binary file added
    new_file = _make_drive_file("f3", "doc.pdf", "application/pdf", size=300)
    from gdrive_backup.drive_client import DriveChange
    change = MagicMock(spec=DriveChange)
    change.file_id = "f3"
    change.removed = False
    change.file = new_file
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

    # Full scan to add file first
    s["mock_drive"].list_all_files.return_value = [s["text_file"]]
    s["mock_drive"].download_file.return_value = b"to be deleted"
    s["engine"].run_full_scan()

    # Incremental with deletion
    from gdrive_backup.drive_client import DriveChange
    del_change = MagicMock(spec=DriveChange)
    del_change.file_id = "f1"
    del_change.removed = True
    del_change.file = None
    s["mock_drive"].get_changes.return_value = ([del_change], "token-003")

    stats = s["engine"].run_incremental()

    assert stats.deleted == 1
    git_files = list(s["git_path"].rglob("*.txt"))
    assert len(git_files) == 0
```

- [ ] **Step 2: Run to verify all pass**

```bash
pytest tests/test_e2e.py -v
```
Expected: all 4 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: add mock-based end-to-end sync engine tests"
```

---

## Task 10: Run full test suite

- [ ] **Step 1: Run all tests**

```bash
pytest --cov=gdrive_backup --cov-report=term-missing -v
```
Expected: all tests pass; no regressions.

- [ ] **Step 2: Fix any failures before continuing**

---

## Task 11: GitHub Actions `ci.yml`

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create the workflow file**

```bash
mkdir -p .github/workflows
```

Create `.github/workflows/ci.yml`:

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  test:
    name: Test (Python ${{ matrix.python-version }})
    runs-on: ubuntu-latest
    strategy:
      fail-fast: false
      matrix:
        python-version: ["3.10", "3.11", "3.12"]

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python ${{ matrix.python-version }}
        uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Configure git identity for tests
        run: |
          git config --global user.email "ci@gdrive-backup"
          git config --global user.name "CI"

      - name: Run tests with coverage
        run: pytest --cov=gdrive_backup --cov-report=xml --cov-report=term-missing -v

      - name: Upload coverage
        if: matrix.python-version == '3.11'
        uses: actions/upload-artifact@v4
        with:
          name: coverage-report
          path: coverage.xml
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add unit test workflow with Python 3.10-3.12 matrix"
```

---

## Task 12: GitHub Actions `e2e.yml`

**Files:**
- Create: `.github/workflows/e2e.yml`

- [ ] **Step 1: Create the workflow file**

Create `.github/workflows/e2e.yml`:

```yaml
name: E2E Backup

on:
  workflow_dispatch:
    inputs:
      output_mode:
        description: "GitHub output mode"
        required: true
        default: new_repo
        type: choice
        options:
          - new_repo
          - new_branch

jobs:
  e2e:
    name: Real end-to-end backup
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v4

      - name: Set up Python 3.11
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Install dependencies
        run: pip install -e ".[dev]"

      - name: Configure git identity
        run: |
          git config --global user.email "e2e@gdrive-backup"
          git config --global user.name "E2E"

      - name: Write Google Drive credentials
        run: |
          echo "${{ secrets.GDRIVE_CREDENTIALS_JSON }}" | base64 -d > /tmp/gdrive_credentials.json
          echo "${{ secrets.GDRIVE_TOKEN_JSON }}" | base64 -d > /tmp/gdrive_token.json
          chmod 600 /tmp/gdrive_credentials.json /tmp/gdrive_token.json

      - name: Write e2e config
        run: |
          echo "${{ secrets.E2E_CONFIG_TEMPLATE }}" | base64 -d > /tmp/e2e_config.yaml
          # Substitute the output_mode placeholder
          if ! grep -q "__OUTPUT_MODE__" /tmp/e2e_config.yaml; then
            echo "ERROR: __OUTPUT_MODE__ placeholder not found in E2E_CONFIG_TEMPLATE secret"
            exit 1
          fi
          sed -i "s/__OUTPUT_MODE__/${{ inputs.output_mode }}/g" /tmp/e2e_config.yaml
          chmod 600 /tmp/e2e_config.yaml

      - name: Run backup
        env:
          GITHUB_PAT: ${{ secrets.GITHUB_PAT_E2E }}
        run: gdrive-backup run --config /tmp/e2e_config.yaml

      - name: Print results
        if: success()
        run: |
          echo "=== Git log ==="
          git -C /tmp/e2e-gdrive-repo log --oneline | head -20 || echo "(no commits)"
          echo "=== Mirror contents ==="
          find /tmp/e2e-gdrive-mirror -type f | head -40 || echo "(empty)"
          echo "=== State summary ==="
          python -c "
          import json, sys
          state = json.load(open('/tmp/e2e-state.json'))
          cache = state.get('file_cache', {})
          text = sum(1 for v in cache.values() if v.get('type') == 'text')
          binary = len(cache) - text
          print(f'Files in state: {len(cache)} ({text} text, {binary} binary)')
          print(f'Last run: {state.get(\"last_run\", \"unknown\")}')
          print(f'Status: {state.get(\"last_run_status\", \"unknown\")}')
          "

      - name: Cleanup e2e outputs
        if: always()
        env:
          GITHUB_PAT: ${{ secrets.GITHUB_PAT_E2E }}
        run: |
          python scripts/cleanup_e2e.py \
            --delete --yes \
            --mode ${{ inputs.output_mode }} \
            --base-repo eyal050/gdrive-backup-data \
            --repo-dir /tmp/e2e-gdrive-repo \
            --mirror-dir /tmp/e2e-gdrive-mirror \
            --owner eyal050
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/e2e.yml
git commit -m "ci: add real end-to-end backup workflow with manual dispatch"
```

---

## Task 13: Cleanup script (`scripts/cleanup_e2e.py`)

**Files:**
- Create: `scripts/cleanup_e2e.py`

- [ ] **Step 1: Create the script**

```bash
mkdir -p scripts
```

Create `scripts/cleanup_e2e.py`:

```python
#!/usr/bin/env python3
"""
Delete e2e test outputs: timestamped GitHub repos/branches and local directories.

Usage:
  python scripts/cleanup_e2e.py                    # list only
  python scripts/cleanup_e2e.py --delete --yes     # delete without prompt
  python scripts/cleanup_e2e.py --mode new_branch --base-repo alice/backup-data
"""
import argparse
import os
import re
import shutil
import sys
from typing import Iterator

import requests

E2E_PATTERN = re.compile(r"^\d{2}-\d{2}-\d{4}-\d{2}-\d{2}_gdrive-backup$")
BASE_URL = "https://api.github.com"


def _session(pat: str) -> requests.Session:
    s = requests.Session()
    s.headers.update(
        {
            "Authorization": f"token {pat}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
    )
    return s


def _paginate(session: requests.Session, url: str) -> Iterator[dict]:
    """Yield all items from a paginated GitHub API endpoint."""
    while url:
        resp = session.get(url, timeout=10)
        resp.raise_for_status()
        yield from resp.json()
        url = None
        link = resp.headers.get("Link", "")
        for part in link.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                break


def list_matching_repos(session: requests.Session, owner: str) -> list[str]:
    """Return repo names matching the e2e pattern under owner."""
    url = f"{BASE_URL}/users/{owner}/repos?per_page=100"
    matches = []
    try:
        for repo in _paginate(session, url):
            if E2E_PATTERN.match(repo["name"]):
                matches.append(repo["name"])
    except requests.HTTPError as e:
        # Try org endpoint if user endpoint fails
        url = f"{BASE_URL}/orgs/{owner}/repos?per_page=100"
        for repo in _paginate(session, url):
            if E2E_PATTERN.match(repo["name"]):
                matches.append(repo["name"])
    return sorted(matches)


def list_matching_branches(session: requests.Session, base_repo: str) -> list[str]:
    """Return branch names matching the e2e pattern on base_repo (owner/repo)."""
    url = f"{BASE_URL}/repos/{base_repo}/branches?per_page=100"
    matches = []
    for branch in _paginate(session, url):
        if E2E_PATTERN.match(branch["name"]):
            matches.append(branch["name"])
    return sorted(matches)


def delete_repo(session: requests.Session, owner: str, repo: str) -> None:
    resp = session.delete(f"{BASE_URL}/repos/{owner}/{repo}", timeout=10)
    if resp.status_code == 204:
        print(f"  Deleted repo: {owner}/{repo}")
    elif resp.status_code == 404:
        print(f"  Already gone: {owner}/{repo}")
    else:
        print(f"  ERROR deleting {owner}/{repo}: HTTP {resp.status_code}", file=sys.stderr)


def delete_branch(session: requests.Session, base_repo: str, branch: str) -> None:
    resp = session.delete(
        f"{BASE_URL}/repos/{base_repo}/git/refs/heads/{branch}", timeout=10
    )
    if resp.status_code == 204:
        print(f"  Deleted branch: {branch} on {base_repo}")
    elif resp.status_code == 422:
        print(f"  Already gone: {branch}")
    else:
        print(f"  ERROR deleting branch {branch}: HTTP {resp.status_code}", file=sys.stderr)


def delete_local_dir(path: str) -> None:
    p = os.path.expanduser(path)
    if os.path.exists(p):
        shutil.rmtree(p)
        print(f"  Deleted local dir: {p}")
    else:
        print(f"  Not found (already clean): {p}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Clean up e2e test outputs")
    parser.add_argument("--delete", action="store_true", help="Delete matched items (default: list only)")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    parser.add_argument("--mode", choices=["new_repo", "new_branch"], default="new_repo")
    parser.add_argument("--base-repo", default=None, metavar="OWNER/REPO",
                        help="Required with --mode new_branch")
    parser.add_argument("--repo-dir", default=None, metavar="PATH",
                        help="Local git repo directory to delete")
    parser.add_argument("--mirror-dir", default=None, metavar="PATH",
                        help="Local mirror directory to delete")
    parser.add_argument("--pat", default=None,
                        help="GitHub PAT (default: GITHUB_PAT env var; prefer env var for interactive use)")
    parser.add_argument("--owner", default=None,
                        help="GitHub owner (default: GITHUB_OWNER env var, then prompt)")
    args = parser.parse_args()

    # Validate
    if args.mode == "new_branch" and not args.base_repo:
        print("ERROR: --base-repo is required with --mode new_branch", file=sys.stderr)
        sys.exit(2)

    # Resolve PAT
    pat = args.pat or os.environ.get("GITHUB_PAT")
    if not pat:
        print("ERROR: No PAT provided. Set GITHUB_PAT env var or use --pat.", file=sys.stderr)
        sys.exit(1)

    # Resolve owner
    owner = args.owner or os.environ.get("GITHUB_OWNER")
    if not owner and args.mode == "new_repo":
        owner = input("GitHub owner: ").strip()
    if not owner and args.mode == "new_repo":
        print("ERROR: owner is required", file=sys.stderr)
        sys.exit(1)

    session = _session(pat)

    # Find matches
    if args.mode == "new_repo":
        matches = list_matching_repos(session, owner)
        kind = "repos"
    else:
        matches = list_matching_branches(session, args.base_repo)
        kind = f"branches on {args.base_repo}"

    if not matches:
        print(f"No e2e {kind} found matching pattern.")
    else:
        print(f"\nFound {len(matches)} e2e {kind}:")
        for m in matches:
            print(f"  {m}")

    if not args.delete:
        if matches:
            print("\n(use --delete to remove them)")
        return

    # Confirm
    if not args.yes:
        answer = input(f"\nDelete the above? [y/N] ").strip().lower()
        if answer != "y":
            print("Aborted.")
            return

    print("\nDeleting...")
    if args.mode == "new_repo":
        for name in matches:
            delete_repo(session, owner, name)
    else:
        for name in matches:
            delete_branch(session, args.base_repo, name)

    if args.repo_dir:
        delete_local_dir(args.repo_dir)
    if args.mirror_dir:
        delete_local_dir(args.mirror_dir)

    print("Done.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Make executable and verify it runs**

```bash
chmod +x scripts/cleanup_e2e.py
python scripts/cleanup_e2e.py --help
```
Expected: usage message printed, no errors.

- [ ] **Step 3: Commit**

```bash
git add scripts/cleanup_e2e.py
git commit -m "feat: add cleanup_e2e.py script for deleting e2e test outputs"
```

---

## Task 14: Update `config.example.yaml`

**Files:**
- Modify: `config.example.yaml`

- [ ] **Step 1: Add `github` section**

Append to `config.example.yaml`:

```yaml

# GitHub push (optional)
# Leave pat blank to use the GITHUB_PAT environment variable instead
github:
  enabled: false
  pat: ""
  owner: "your-github-username"
  repo: "gdrive-backup-data"
  private: true
  auto_create: true
  # e2e:                        # Only needed for CI/CD end-to-end runs
  #   output_mode: new_repo     # "new_repo" or "new_branch"
  #   base_repo: "gdrive-backup-data"
```

- [ ] **Step 2: Commit**

```bash
git add config.example.yaml
git commit -m "docs: add github section to example config"
```

---

## Task 15: Final check

- [ ] **Step 1: Run full test suite**

```bash
pytest --cov=gdrive_backup --cov-report=term-missing -v
```
Expected: all tests pass, no regressions.

- [ ] **Step 2: Smoke test dry run CLI**

```bash
gdrive-backup --help
gdrive-backup run --help
```
Verify `--dry-run` flag appears in help output.

- [ ] **Step 3: Push code to GitHub**

```bash
git push origin main
```

Verify CI workflow triggers and passes on GitHub Actions.
