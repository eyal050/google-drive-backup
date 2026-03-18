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
    except requests.HTTPError:
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
                        help="GitHub PAT (default: GITHUB_PAT env var)")
    parser.add_argument("--owner", default=None,
                        help="GitHub owner (default: GITHUB_OWNER env var, then prompt)")
    args = parser.parse_args()

    if args.mode == "new_branch" and not args.base_repo:
        print("ERROR: --base-repo is required with --mode new_branch", file=sys.stderr)
        sys.exit(2)

    pat = args.pat or os.environ.get("GITHUB_PAT")
    if not pat:
        print("ERROR: No PAT provided. Set GITHUB_PAT env var or use --pat.", file=sys.stderr)
        sys.exit(1)

    owner = args.owner or os.environ.get("GITHUB_OWNER")
    if not owner and args.mode == "new_repo":
        owner = input("GitHub owner: ").strip()
    if not owner and args.mode == "new_repo":
        print("ERROR: owner is required", file=sys.stderr)
        sys.exit(1)

    session = _session(pat)

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
