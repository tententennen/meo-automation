"""Tests for meo.drive — all Google API calls are mocked."""

from __future__ import annotations

import io
import pytest
from unittest.mock import MagicMock, patch, call

from meo.drive import DriveClient, _IMAGE_MIMES


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_drive_client() -> tuple[DriveClient, MagicMock]:
    """Return (DriveClient, mock_service) with the Drive service mocked out."""
    mock_service = MagicMock()
    with patch("meo.drive.build", return_value=mock_service):
        client = DriveClient(credentials=MagicMock())
    return client, mock_service


def _files_list_response(files: list, next_token: str | None = None) -> dict:
    r: dict = {"files": files}
    if next_token:
        r["nextPageToken"] = next_token
    return r


# ---------------------------------------------------------------------------
# list_images
# ---------------------------------------------------------------------------

class TestListImages:
    def test_returns_image_files(self):
        client, svc = _make_drive_client()
        files = [
            {"id": "1", "name": "a.jpg", "mimeType": "image/jpeg", "webContentLink": "https://drive.google.com/uc?id=1"},
            {"id": "2", "name": "b.png", "mimeType": "image/png", "webContentLink": "https://drive.google.com/uc?id=2"},
        ]
        svc.files().list().execute.return_value = _files_list_response(files)

        result = client.list_images("folder123")

        assert len(result) == 2
        assert result[0]["id"] == "1"

    def test_returns_empty_list_when_no_files(self):
        client, svc = _make_drive_client()
        svc.files().list().execute.return_value = _files_list_response([])

        result = client.list_images("empty_folder")

        assert result == []

    def test_query_filters_by_folder_and_mime_types(self):
        client, svc = _make_drive_client()
        svc.files().list().execute.return_value = _files_list_response([])

        client.list_images("myfolder42")

        call_kwargs = svc.files().list.call_args.kwargs
        q = call_kwargs["q"]
        assert "'myfolder42' in parents" in q
        assert "trashed = false" in q
        for mime in _IMAGE_MIMES:
            assert mime in q

    def test_follows_pagination(self):
        client, svc = _make_drive_client()
        page1 = _files_list_response([{"id": "1", "name": "a.jpg", "mimeType": "image/jpeg"}], next_token="tok2")
        page2 = _files_list_response([{"id": "2", "name": "b.jpg", "mimeType": "image/jpeg"}])
        # Access via return_value to avoid recording a spurious list() call
        svc.files.return_value.list.return_value.execute.side_effect = [page1, page2]

        result = client.list_images("folder")

        assert len(result) == 2
        assert svc.files.return_value.list.return_value.execute.call_count == 2
        # Verify the second list() call included the pageToken
        calls = svc.files.return_value.list.call_args_list
        assert any(c.kwargs.get("pageToken") == "tok2" for c in calls)

    def test_includes_required_fields(self):
        client, svc = _make_drive_client()
        svc.files().list().execute.return_value = _files_list_response([])

        client.list_images("folder")

        call_kwargs = svc.files().list.call_args.kwargs
        fields = call_kwargs["fields"]
        assert "id" in fields
        assert "name" in fields
        assert "mimeType" in fields


# ---------------------------------------------------------------------------
# pick_random_image
# ---------------------------------------------------------------------------

class TestPickRandomImage:
    def test_returns_none_for_empty_folder(self):
        client, svc = _make_drive_client()
        svc.files().list().execute.return_value = _files_list_response([])

        result = client.pick_random_image("empty")

        assert result is None

    def test_returns_one_of_available_images(self):
        client, svc = _make_drive_client()
        files = [
            {"id": "1", "name": "a.jpg", "mimeType": "image/jpeg"},
            {"id": "2", "name": "b.jpg", "mimeType": "image/jpeg"},
            {"id": "3", "name": "c.png", "mimeType": "image/png"},
        ]
        svc.files().list().execute.return_value = _files_list_response(files)

        result = client.pick_random_image("folder")

        assert result is not None
        assert result["id"] in {"1", "2", "3"}

    def test_returns_only_image_when_single(self):
        client, svc = _make_drive_client()
        files = [{"id": "solo", "name": "only.jpg", "mimeType": "image/jpeg"}]
        svc.files().list().execute.return_value = _files_list_response(files)

        result = client.pick_random_image("folder")

        assert result is not None
        assert result["id"] == "solo"


# ---------------------------------------------------------------------------
# download_image
# ---------------------------------------------------------------------------

class TestDownloadImage:
    def test_returns_bytes(self):
        client, svc = _make_drive_client()
        expected = b"\xff\xd8\xff\xe0" + b"\x00" * 100  # fake JPEG header

        mock_request = MagicMock()
        svc.files().get_media.return_value = mock_request

        chunks = [(MagicMock(), False), (MagicMock(), True)]

        def fake_next_chunk():
            status, done = chunks.pop(0)
            # Write some bytes on each chunk call
            return status, done

        # We need to simulate MediaIoBaseDownload writing to the buffer.
        # Patch MediaIoBaseDownload so it writes expected bytes to the buf.
        with patch("meo.drive.MediaIoBaseDownload") as mock_dl_cls:
            mock_dl = MagicMock()
            call_count = [0]

            def next_chunk_side_effect():
                call_count[0] += 1
                done = call_count[0] >= 2
                return MagicMock(), done

            mock_dl.next_chunk.side_effect = next_chunk_side_effect
            mock_dl_cls.side_effect = lambda buf, req: _write_and_return(buf, expected, mock_dl)

            result = client.download_image("file99")

        assert result == expected

    def test_calls_get_media_with_file_id(self):
        client, svc = _make_drive_client()
        expected = b"pngdata"

        with patch("meo.drive.MediaIoBaseDownload") as mock_dl_cls:
            mock_dl = MagicMock()
            mock_dl.next_chunk.return_value = (MagicMock(), True)
            mock_dl_cls.side_effect = lambda buf, req: _write_and_return(buf, expected, mock_dl)

            client.download_image("specific_file_id")

        svc.files().get_media.assert_called_once_with(fileId="specific_file_id")


def _write_and_return(buf: io.BytesIO, data: bytes, mock_dl: MagicMock) -> MagicMock:
    """Helper: write data into buf (simulating what MediaIoBaseDownload does) and return mock."""
    buf.write(data)
    buf.seek(0)
    return mock_dl
