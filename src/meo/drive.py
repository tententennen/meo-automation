"""Google Drive client — list and download images from a store's Drive folder.

Uses the Drive API v3 via the official google-api-python-client.
Scope required: https://www.googleapis.com/auth/drive.readonly
This scope is already included in auth.SCOPES so no extra credential is needed.

Ref: https://developers.google.com/drive/api/v3/reference/files/list
"""

from __future__ import annotations

import logging
import random
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google.oauth2.credentials import Credentials

import io

logger = logging.getLogger(__name__)

# MIME types considered valid post images
_IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}


class DriveClient:
    """Fetch images from a Google Drive folder."""

    def __init__(self, credentials: Credentials) -> None:
        self._service = build("drive", "v3", credentials=credentials)

    def list_images(self, folder_id: str) -> list[dict[str, Any]]:
        """Return metadata for all image files in a Drive folder.

        Each item has at minimum: id, name, mimeType, webContentLink, size.
        The size field is a string integer (bytes); absent on files whose size
        is not tracked by Drive (treat as 0 — include in selection).
        """
        query = (
            f"'{folder_id}' in parents"
            " and trashed = false"
            " and ("
            + " or ".join(f"mimeType = '{m}'" for m in _IMAGE_MIMES)
            + ")"
        )
        results: list[dict[str, Any]] = []
        page_token: str | None = None

        while True:
            kwargs: dict[str, Any] = {
                "q": query,
                "spaces": "drive",
                "fields": "nextPageToken, files(id, name, mimeType, webContentLink, size)",
                "pageSize": 100,
            }
            if page_token:
                kwargs["pageToken"] = page_token

            response = (
                self._service.files().list(**kwargs).execute()
            )
            results.extend(response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        logger.info("Found %d images in Drive folder %s", len(results), folder_id)
        return results

    def pick_random_image(
        self,
        folder_id: str,
        *,
        recent_ids: list[str] | None = None,
        max_bytes: int | None = None,
    ) -> dict[str, Any] | None:
        """Return metadata for a randomly selected image in the folder, or None.

        Args:
            folder_id:  Drive folder ID to list images from.
            recent_ids: Image IDs used in recent posts.  Fresh images (not in
                        this list) are preferred; falls back to any image when
                        all have been recently used.
            max_bytes:  If set, images whose ``size`` field exceeds this value
                        are excluded.  Images with no ``size`` field are always
                        included.  Returns None (instead of an oversized image)
                        when every image in the folder exceeds the limit.
                        Default GBP upload limit: 5 242 880 bytes (5 MB).
        """
        images = self.list_images(folder_id)
        if not images:
            logger.warning("No images found in Drive folder %s", folder_id)
            return None

        if max_bytes is not None:
            valid = [
                img for img in images
                if int(img.get("size") or 0) <= max_bytes
            ]
            if not valid:
                logger.warning(
                    "All %d image(s) in Drive folder %s exceed the %d-byte size limit; "
                    "skipping photo attachment.",
                    len(images), folder_id, max_bytes,
                )
                return None
            if len(valid) < len(images):
                logger.debug(
                    "Filtered %d oversized image(s) from folder %s (%d remain).",
                    len(images) - len(valid), folder_id, len(valid),
                )
            images = valid

        if recent_ids:
            recent = set(recent_ids)
            fresh = [img for img in images if img["id"] not in recent]
            if fresh:
                logger.debug(
                    "Picking from %d fresh image(s) (skipping %d recently used) in folder %s",
                    len(fresh), len(images) - len(fresh), folder_id,
                )
                return random.choice(fresh)
            logger.info(
                "All %d image(s) in folder %s recently used; picking any at random.",
                len(images), folder_id,
            )
        return random.choice(images)

    def get_image_metadata(self, file_id: str) -> dict[str, Any]:
        """Return metadata for a specific Drive file by ID.

        Returns a dict with at minimum: id, name, mimeType, webContentLink.
        Raises googleapiclient.errors.HttpError if the file is not found
        or the caller lacks read permission.

        Ref: https://developers.google.com/drive/api/v3/reference/files/get
        """
        return (
            self._service.files()
            .get(fileId=file_id, fields="id, name, mimeType, webContentLink")
            .execute()
        )

    def download_image(self, file_id: str) -> bytes:
        """Download a Drive file's binary content (authenticated — works for private files).

        Callers pass the returned bytes to BusinessProfileClient.upload_media_bytes()
        which re-hosts the image on GBP and returns a public googleUrl for the post.
        """
        request = self._service.files().get_media(fileId=file_id)
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buf.getvalue()
