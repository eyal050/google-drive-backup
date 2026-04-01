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
        logger.debug(f"DriveClient initialized (max_retries={max_retries})")

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
        logger.info(f"Listing files with query: {query}")
        page_token = None
        file_count = 0
        page_num = 0

        while True:
            page_num += 1
            self._limiter.wait()
            logger.debug(f"Fetching file list page {page_num} (pageToken={'yes' if page_token else 'none'})")

            try:
                response = self._execute_with_retry(
                    self._service.files().list(
                        q=query,
                        fields=f"nextPageToken, files({self.FILE_FIELDS})",
                        pageSize=1000,
                        pageToken=page_token,
                    )
                )
            except Exception as e:
                logger.error(f"Failed to list files (page {page_num}, {file_count} files so far): {e}")
                raise

            files_in_page = response.get("files", [])
            logger.debug(f"Page {page_num}: received {len(files_in_page)} files")

            for f in files_in_page:
                file_count += 1
                if file_count % 100 == 0:
                    logger.info(f"Listed {file_count} files...")
                try:
                    yield self._parse_file(f)
                except Exception as e:
                    logger.error(f"Failed to parse file data: {f.get('name', 'unknown')}: {e}")
                    continue

            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"Listed {file_count} files total across {page_num} pages")

    def count_files(
        self,
        include_shared: bool = False,
        folder_ids: Optional[List[str]] = None,
    ) -> int:
        """Count total files in Drive without downloading metadata.

        Uses the same query as list_all_files but requests only file IDs
        for efficiency.
        """
        query_parts = ["trashed = false"]
        if not include_shared:
            query_parts.append("'me' in owners")
        if folder_ids:
            folder_q = " or ".join(f"'{fid}' in parents" for fid in folder_ids)
            query_parts.append(f"({folder_q})")

        query = " and ".join(query_parts)
        logger.info(f"Counting files with query: {query}")
        page_token = None
        total = 0

        while True:
            self._limiter.wait()
            try:
                response = self._execute_with_retry(
                    self._service.files().list(
                        q=query,
                        fields="nextPageToken, files(id)",
                        pageSize=1000,
                        pageToken=page_token,
                    )
                )
            except Exception as e:
                logger.error(f"Failed to count files ({total} counted so far): {e}")
                raise

            total += len(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info(f"Total files counted: {total}")
        return total

    def get_start_page_token(self) -> str:
        """Get the current start page token for changes API."""
        logger.debug("Getting start page token for changes API")
        self._limiter.wait()
        try:
            response = self._execute_with_retry(
                self._service.changes().getStartPageToken()
            )
            token = response["startPageToken"]
            logger.debug(f"Got start page token: {token}")
            return token
        except Exception as e:
            logger.error(f"Failed to get start page token: {e}")
            raise

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
        page_num = 0

        logger.info(f"Fetching changes since token: {start_page_token}")

        while page_token:
            page_num += 1
            self._limiter.wait()
            logger.debug(f"Fetching changes page {page_num}")

            try:
                response = self._execute_with_retry(
                    self._service.changes().list(
                        pageToken=page_token,
                        fields=f"nextPageToken, newStartPageToken, changes(fileId, removed, file({self.FILE_FIELDS}, trashed))",
                        pageSize=1000,
                    )
                )
            except Exception as e:
                logger.error(f"Failed to fetch changes (page {page_num}): {e}")
                raise

            changes_in_page = response.get("changes", [])
            logger.debug(f"Changes page {page_num}: {len(changes_in_page)} changes")

            for change in changes_in_page:
                try:
                    file_data = change.get("file")
                    removed = change.get("removed", False)
                    trashed = file_data.get("trashed", False) if file_data else False

                    drive_file = self._parse_file(file_data) if file_data and not trashed else None

                    all_changes.append(DriveChange(
                        file_id=change["fileId"],
                        removed=removed or trashed,
                        file=drive_file,
                    ))
                except Exception as e:
                    logger.error(
                        f"Failed to parse change entry (fileId={change.get('fileId', 'unknown')}): {e}"
                    )
                    continue

            page_token = response.get("nextPageToken")
            new_start_token = response.get("newStartPageToken")

        logger.info(f"Fetched {len(all_changes)} changes across {page_num} pages")
        return all_changes, new_start_token

    def download_file(self, file_id: str) -> bytes:
        """Download a regular (non-Google-native) file.

        Returns:
            File content as bytes.
        """
        logger.debug(f"Downloading file: {file_id}")
        self._limiter.wait()
        try:
            request = self._service.files().get_media(fileId=file_id)
            content = self._download_media(request)
            logger.debug(f"Downloaded {len(content)} bytes for file {file_id}")
            return content
        except HttpError as e:
            logger.error(f"HTTP error downloading file {file_id}: status={e.resp.status}, detail={e}")
            raise
        except Exception as e:
            logger.error(f"Failed to download file {file_id}: {e}")
            raise

    def export_file(self, file_id: str, mime_type: str) -> bytes:
        """Export a Google native file to the specified MIME type.

        Returns:
            Exported file content as bytes.
        """
        logger.debug(f"Exporting file {file_id} as {mime_type}")
        self._limiter.wait()
        try:
            request = self._service.files().export_media(fileId=file_id, mimeType=mime_type)
            content = self._download_media(request)
            logger.debug(f"Exported {len(content)} bytes for file {file_id}")
            return content
        except HttpError as e:
            logger.error(f"HTTP error exporting file {file_id}: status={e.resp.status}, detail={e}")
            raise
        except Exception as e:
            logger.error(f"Failed to export file {file_id}: {e}")
            raise

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
        depth = 0
        max_depth = 50  # Guard against circular references

        while current_id and depth < max_depth:
            depth += 1
            if current_id in self._path_cache:
                cached = self._path_cache[current_id]
                if cached:
                    parts.append(cached)
                break

            self._limiter.wait()
            try:
                folder = self._execute_with_retry(
                    self._service.files().get(
                        fileId=current_id, fields="name, parents"
                    )
                )
            except HttpError as e:
                if e.resp.status == 404:
                    logger.debug(f"Parent folder {current_id} not found (possibly root or deleted)")
                else:
                    logger.warning(f"Failed to resolve parent {current_id}: {e}")
                break
            except Exception as e:
                logger.warning(f"Error resolving parent {current_id}: {e}")
                break

            parents = folder.get("parents", [])
            if not parents:
                break  # Reached root

            parts.append(folder["name"])
            current_id = parents[0]

        if depth >= max_depth:
            logger.warning(f"Path resolution exceeded max depth ({max_depth}) for parent {parent_id}")

        parts.reverse()
        path = "/".join(parts)
        self._path_cache[parent_id] = path
        return path

    def _download_media(self, request) -> bytes:
        """Download media content from a request object."""
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        chunk_num = 0
        while not done:
            try:
                status, done = downloader.next_chunk()
                chunk_num += 1
                if status and chunk_num % 10 == 0:
                    logger.debug(f"Download progress: {int(status.progress() * 100)}%")
            except HttpError as e:
                logger.error(f"HTTP error during media download (chunk {chunk_num}): {e}")
                raise
            except Exception as e:
                logger.error(f"Error during media download (chunk {chunk_num}): {e}")
                raise
        return buffer.getvalue()

    def _execute_with_retry(self, request):
        """Execute an API request with retry logic."""
        for attempt in range(self._max_retries):
            try:
                return request.execute()
            except HttpError as e:
                if e.resp.status == 429:
                    retry_after = int(e.resp.get("Retry-After", 2 ** attempt))
                    logger.warning(
                        f"Rate limited (429). Attempt {attempt+1}/{self._max_retries}. "
                        f"Retrying in {retry_after}s..."
                    )
                    self._limiter.reduce_rate()
                    time.sleep(retry_after)
                elif e.resp.status >= 500:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Server error {e.resp.status}. Attempt {attempt+1}/{self._max_retries}. "
                        f"Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                elif e.resp.status == 403:
                    logger.error(
                        f"Permission denied (403): {e}. "
                        f"Check that the Drive API is enabled and scopes are correct."
                    )
                    raise
                elif e.resp.status == 404:
                    logger.debug(f"Resource not found (404): {e}")
                    raise
                else:
                    logger.error(f"HTTP error {e.resp.status}: {e}")
                    raise
            except Exception as e:
                if attempt < self._max_retries - 1:
                    wait = 2 ** attempt
                    logger.warning(
                        f"Request failed: {e}. Attempt {attempt+1}/{self._max_retries}. "
                        f"Retrying in {wait}s..."
                    )
                    time.sleep(wait)
                else:
                    logger.error(f"Request failed after {self._max_retries} attempts: {e}")
                    raise

        raise RuntimeError(f"Request failed after {self._max_retries} retries")

    def _parse_file(self, data: dict) -> DriveFile:
        """Parse API response dict into DriveFile."""
        size_str = data.get("size")
        return DriveFile(
            id=data["id"],
            name=data.get("name", "unnamed"),
            mime_type=data.get("mimeType", "application/octet-stream"),
            parents=data.get("parents", []),
            md5=data.get("md5Checksum"),
            size=int(size_str) if size_str else None,
            modified_time=data.get("modifiedTime", ""),
        )
