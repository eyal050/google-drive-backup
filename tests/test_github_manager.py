"""Unit tests for GithubManager — all HTTP calls are mocked."""
import pytest
import requests as req
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
