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
