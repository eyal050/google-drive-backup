# tests/test_classifier.py
"""Tests for file type classification."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from gdrive_backup.classifier import (
    FileClassifier,
    FileType,
    sanitize_filename,
)


class TestSanitizeFilename:
    def test_normal_name_unchanged(self):
        assert sanitize_filename("report.txt") == "report.txt"

    def test_strips_path_traversal(self):
        assert ".." not in sanitize_filename("../../etc/passwd")

    def test_strips_absolute_path(self):
        result = sanitize_filename("/etc/passwd")
        assert not result.startswith("/")

    def test_replaces_null_bytes(self):
        assert "\x00" not in sanitize_filename("file\x00name.txt")

    def test_empty_name_gets_default(self):
        result = sanitize_filename("")
        assert len(result) > 0


class TestFileClassifier:
    @pytest.fixture
    def classifier(self):
        return FileClassifier()

    def test_text_mime_classified_as_text(self, classifier):
        assert classifier.classify_by_mime("text/plain") == FileType.TEXT
        assert classifier.classify_by_mime("text/html") == FileType.TEXT
        assert classifier.classify_by_mime("application/json") == FileType.TEXT
        assert classifier.classify_by_mime("application/xml") == FileType.TEXT
        assert classifier.classify_by_mime("application/javascript") == FileType.TEXT
        assert classifier.classify_by_mime("application/x-yaml") == FileType.TEXT
        assert classifier.classify_by_mime("application/x-sh") == FileType.TEXT
        assert classifier.classify_by_mime("application/sql") == FileType.TEXT

    def test_binary_mime_classified_as_binary(self, classifier):
        assert classifier.classify_by_mime("image/png") == FileType.BINARY
        assert classifier.classify_by_mime("image/jpeg") == FileType.BINARY
        assert classifier.classify_by_mime("application/pdf") == FileType.BINARY
        assert classifier.classify_by_mime("video/mp4") == FileType.BINARY
        assert classifier.classify_by_mime("audio/mpeg") == FileType.BINARY
        assert classifier.classify_by_mime("application/zip") == FileType.BINARY
        assert classifier.classify_by_mime("application/octet-stream") == FileType.BINARY

    def test_office_formats_classified_as_binary(self, classifier):
        assert classifier.classify_by_mime(
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
        ) == FileType.BINARY

    def test_google_native_classified_as_binary(self, classifier):
        # Google native types are exported to Office formats = binary
        assert classifier.classify_by_mime(
            "application/vnd.google-apps.document"
        ) == FileType.BINARY

    def test_unknown_mime_returns_unknown(self, classifier):
        assert classifier.classify_by_mime("application/x-unknown-thing") == FileType.UNKNOWN

    def test_classify_by_content_text(self, classifier):
        content = b"Hello, this is plain text content.\nWith newlines.\n"
        assert classifier.classify_by_content(content) == FileType.TEXT

    def test_classify_by_content_binary(self, classifier):
        content = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
        assert classifier.classify_by_content(content) == FileType.BINARY

    def test_classify_combined_uses_mime_first(self, classifier):
        result = classifier.classify("text/plain", b"\x89PNG binary content")
        assert result == FileType.TEXT  # MIME takes priority

    def test_classify_combined_falls_back_to_content(self, classifier):
        result = classifier.classify("application/x-unknown-thing", b"plain text here")
        assert result == FileType.TEXT  # Content detection fallback


class TestDuplicateNameResolution:
    @pytest.fixture
    def classifier(self):
        return FileClassifier()

    def test_first_file_gets_clean_name(self, classifier):
        path = classifier.resolve_local_path("documents", "report.txt", "id1", {})
        assert path == "documents/report.txt"

    def test_duplicate_gets_id_suffix(self, classifier):
        existing = {"id0": {"local_path": "documents/report.txt"}}
        path = classifier.resolve_local_path("documents", "report.txt", "id1", existing)
        assert path == "documents/report (id1).txt"

    def test_cached_path_is_stable(self, classifier):
        existing = {"id1": {"local_path": "documents/report (id1).txt"}}
        path = classifier.resolve_local_path("documents", "report.txt", "id1", existing)
        assert path == "documents/report (id1).txt"
