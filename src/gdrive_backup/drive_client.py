# src/gdrive_backup/drive_client.py
"""Google Drive API wrapper with rate limiting and pagination."""

import io
import logging
import time
from dataclasses import dataclass
from typing import Generator, List, Optional, Tuple

from googleapiclient.http import MediaIoBaseDownload
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# Google native MIME types that need export
GOOGLE_EXPORT_MAP = {
    "application/vnd.google-apps.document": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.google-apps.spreadsheet": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.google-apps.presentation": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}

GOOGLE_EXPORT_EXTENSIONS = {
    "application/vnd.google-apps.document": ".docx",
    "application/vnd.google-apps.spreadsheet": ".xlsx",
    "application/vnd.google-apps.presentation": ".pptx",
}

# Google native types that can't be downloaded (no export available)
GOOGLE_SKIP_TYPES = {
    "application/vnd.google-apps.form",
    "application/vnd.google-apps.map",
    "application/vnd.google-apps.site",
    "application/vnd.google-apps.shortcut",
    "application/vnd.google-apps.folder",
}


@dataclass
class DriveFile:
    """Represents a file from Google Drive."""
    id: str
    name: str
    mime_type: str
    parents: List[str]
    md5: Optional[str]
    size: Optional[int]
    modified_time: str

    @property
    def is_google_native(self) -> bool:
        return self.mime_type.startswith("application/vnd.google-apps.")

    @property
    def is_exportable(self) -> bool:
        return self.mime_type in GOOGLE_EXPORT_MAP

    @property
    def should_skip(self) -> bool:
        return self.mime_type in GOOGLE_SKIP_TYPES

    @property
    def export_mime_type(self) -> Optional[str]:
        return GOOGLE_EXPORT_MAP.get(self.mime_type)

    @property
    def export_extension(self) -> Optional[str]:
        return GOOGLE_EXPORT_EXTENSIONS.get(self.mime_type)


@dataclass
class DriveChange:
    """Represents a change from the Drive changes API."""
    file_id: str
    removed: bool
    file: Optional[DriveFile]


class RateLimiter:
    """Simple rate limiter using token bucket algorithm."""

    def __init__(self, max_per_second: int = 100):
        self.max_per_second = max_per_second
        self._min_interval = 1.0 / max_per_second
        self._last_request = 0.0

    def wait(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def reduce_rate(self) -> None:
        self.max_per_second = max(1, self.max_per_second // 2)
        self._min_interval = 1.0 / self.max_per_second
        logger.warning(f"Rate reduced to {self.max_per_second} requests/second")


class DriveClient:
    """Wrapper around Google Drive API with rate limiting."""

    FILE_FIELDS = "id, name, mimeType, parents, md5Checksum, size, modifiedTime"

    def __init__(self, service, max_retries: int = 3):
        self._service = service
        self._limiter = RateLimiter()
        self._max_retries = max_retries
        self._path_cache: dict[str, str] = {}

    def list_all_files(
        self,
        include_shared: bool = False,
        folder_ids: Optional[List[str]] = None,
    ) -> Generator[DriveFile, None, None]:
        """List all files in Drive, handling pagination.

        Args:
            include_shared: Include files shared with the user.
            folder_ids: Limit to specific folder IDs. Empty = all.

        Yields:
            DriveFile objects.
        """
        query_parts = ["trashed = false"]
        if not include_shared:
            query_parts.append("'me' in owners")
        if folder_ids:
            folder_q = " or ".join(f"'{fid}' in parents" for fid in folder_ids)
            query_parts.append(f"({folder_q})")

        query = " and ".join(query_parts)
        page_token = None
        file_count = 0

        while True:
            self._limiter.wait()
            response = self._execute_with_retry(
                self._service.files().list(
                    q=query,
                    fields=f"nextPageToken, files({self.FILE_FIELDS})",
                    pageSize=1000,
                    pageToken=page_token,
                )
            )

            for f in response.get("files", []):
                file_count += 1
                if file_count % 100 == 0:
                    logger.info(f"Listed {file_count} files...")
                yield self._parse_file(f)

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"Listed {file_count} files total")

    def get_start_page_token(self) -> str:
        """Get the current start page token for changes API."""
        self._limiter.wait()
        response = self._execute_with_retry(
            self._service.changes().getStartPageToken()
        )
        return response["startPageToken"]

    def get_changes(
        self, start_page_token: str
    ) -> Tuple[List[DriveChange], Optional[str]]:
        """Get changes since the given page token.

        Returns:
            Tuple of (list of changes, new start page token or None if more pages).
        """
        all_changes: List[DriveChange] = []
        page_token = start_page_token
        new_start_token = None

        while page_token:
            self._limiter.wait()
            response = self._execute_with_retry(
                self._service.changes().list(
                    pageToken=page_token,
                    fields=f"nextPageToken, newStartPageToken, changes(fileId, removed, file({self.FILE_FIELDS}, trashed))",
                    pageSize=1000,
                )
            )

            for change in response.get("changes", []):
                file_data = change.get("file")
                removed = change.get("removed", False)
                trashed = file_data.get("trashed", False) if file_data else False

                drive_file = self._parse_file(file_data) if file_data and not trashed else None

                all_changes.append(DriveChange(
                    file_id=change["fileId"],
                    removed=removed or trashed,
                    file=drive_file,
                ))

            page_token = response.get("nextPageToken")
            new_start_token = response.get("newStartPageToken")

        return all_changes, new_start_token

    def download_file(self, file_id: str) -> bytes:
        """Download a regular (non-Google-native) file.

        Returns:
            File content as bytes.
        """
        self._limiter.wait()
        request = self._service.files().get_media(fileId=file_id)
        return self._download_media(request)

    def export_file(self, file_id: str, mime_type: str) -> bytes:
        """Export a Google native file to the specified MIME type.

        Returns:
            Exported file content as bytes.
        """
        self._limiter.wait()
        request = self._service.files().export_media(fileId=file_id, mimeType=mime_type)
        return self._download_media(request)

    def resolve_file_path(self, parent_ids: List[str]) -> str:
        """Resolve parent IDs to a folder path string.

        Uses caching to avoid redundant API calls.
        """
        if not parent_ids:
            return ""

        parent_id = parent_ids[0]  # Files typically have one parent
        if parent_id in self._path_cache:
            return self._path_cache[parent_id]

        parts = []
        current_id = parent_id
        while current_id:
            if current_id in self._path_cache:
                parts.append(self._path_cache[current_id])
                break

            self._limiter.wait()
            try:
                folder = self._execute_with_retry(
                    self._service.files().get(
                        fileId=current_id, fields="name, parents"
                    )
                )
            except Exception:
                break

            parents = folder.get("parents", [])
            if not parents:
                break  # Reached root

            parts.append(folder["name"])
            current_id = parents[0]

        parts.reverse()
        path = "/".join(parts)
        self._path_cache[parent_id] = path
        return path

    def _download_media(self, request) -> bytes:
        """Download media content from a request object."""
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            status, done = downloader.next_chunk()
        return buffer.getvalue()

    def _execute_with_retry(self, request):
        """Execute an API request with retry logic."""
        for attempt in range(self._max_retries):
            try:
                return request.execute()
            except HttpError as e:
                if e.resp.status == 429:
                    retry_after = int(e.resp.get("Retry-After", 2 ** attempt))
                    logger.warning(f"Rate limited. Retrying in {retry_after}s...")
                    self._limiter.reduce_rate()
                    time.sleep(retry_after)
                elif e.resp.status >= 500:
                    wait = 2 ** attempt
                    logger.warning(f"Server error {e.resp.status}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise
            except Exception as e:
                if attempt < self._max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(f"Request failed: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    raise

        raise RuntimeError(f"Request failed after {self._max_retries} retries")

    def _parse_file(self, data: dict) -> DriveFile:
        """Parse API response dict into DriveFile."""
        size_str = data.get("size")
        return DriveFile(
            id=data["id"],
            name=data["name"],
            mime_type=data["mimeType"],
            parents=data.get("parents", []),
            md5=data.get("md5Checksum"),
            size=int(size_str) if size_str else None,
            modified_time=data.get("modifiedTime", ""),
        )
