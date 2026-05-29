"""Tests for DriveClient — mocked googleapiclient so no credentials are needed."""

from unittest.mock import MagicMock, patch
import pytest

from meo.drive import DriveClient


def _make_file(file_id: str, name: str, mime: str = "image/jpeg") -> dict:
    return {
        "id": file_id,
        "name": name,
        "mimeType": mime,
        "webContentLink": f"https://drive.google.com/uc?id={file_id}",
    }


@pytest.fixture
def mock_service():
    """Patch googleapiclient.discovery.build so DriveClient makes no real HTTP calls."""
    with patch("meo.drive.build") as mock_build:
        service = MagicMock()
        mock_build.return_value = service
        yield service


@pytest.fixture
def client(mock_service):
    return DriveClient(MagicMock())


# ---------------------------------------------------------------------------
# list_images
# ---------------------------------------------------------------------------

def test_list_images_returns_files(client, mock_service):
    mock_service.files().list().execute.return_value = {
        "files": [_make_file("f1", "photo.jpg")],
    }
    result = client.list_images("folder_id")
    assert len(result) == 1
    assert result[0]["id"] == "f1"


def test_list_images_returns_empty_list_for_empty_folder(client, mock_service):
    mock_service.files().list().execute.return_value = {"files": []}
    result = client.list_images("folder_id")
    assert result == []


def test_list_images_handles_pagination(client, mock_service):
    mock_service.files().list().execute.side_effect = [
        {"files": [_make_file("f1", "a.jpg")], "nextPageToken": "tok1"},
        {"files": [_make_file("f2", "b.jpg")]},
    ]
    result = client.list_images("folder_id")
    assert len(result) == 2
    assert {r["id"] for r in result} == {"f1", "f2"}


# ---------------------------------------------------------------------------
# pick_random_image
# ---------------------------------------------------------------------------

def test_pick_random_image_returns_one_of_the_available(client, mock_service):
    mock_service.files().list().execute.return_value = {
        "files": [_make_file("f1", "a.jpg"), _make_file("f2", "b.jpg")],
    }
    result = client.pick_random_image("folder_id")
    assert result is not None
    assert result["id"] in {"f1", "f2"}


def test_pick_random_image_returns_none_for_empty_folder(client, mock_service):
    mock_service.files().list().execute.return_value = {"files": []}
    assert client.pick_random_image("folder_id") is None


def test_pick_random_image_prefers_fresh_over_recent(client, mock_service):
    mock_service.files().list().execute.return_value = {
        "files": [_make_file("old_id", "old.jpg"), _make_file("new_id", "new.jpg")],
    }
    result = client.pick_random_image("folder_id", recent_ids=["old_id"])
    assert result is not None
    assert result["id"] == "new_id"


def test_pick_random_image_falls_back_when_all_images_are_recent(client, mock_service):
    mock_service.files().list().execute.return_value = {
        "files": [_make_file("f1", "only.jpg")],
    }
    result = client.pick_random_image("folder_id", recent_ids=["f1"])
    assert result is not None
    assert result["id"] == "f1"


def test_pick_random_image_ignores_recent_ids_when_empty_list(client, mock_service):
    mock_service.files().list().execute.return_value = {
        "files": [_make_file("f1", "photo.jpg")],
    }
    result = client.pick_random_image("folder_id", recent_ids=[])
    assert result is not None
    assert result["id"] == "f1"


# ---------------------------------------------------------------------------
# download_image
# ---------------------------------------------------------------------------

def test_download_image_returns_bytes(client, mock_service):
    fake_bytes = b"\xff\xd8\xff\xe0"  # minimal JPEG header
    mock_request = MagicMock()
    mock_service.files().get_media.return_value = mock_request

    with patch("meo.drive.MediaIoBaseDownload") as MockDL, \
         patch("meo.drive.io.BytesIO") as MockBytesIO:
        buf = MagicMock()
        buf.getvalue.return_value = fake_bytes
        MockBytesIO.return_value = buf

        dl = MagicMock()
        dl.next_chunk.side_effect = [(None, False), (None, True)]
        MockDL.return_value = dl

        result = client.download_image("file_id_123")

    assert result == fake_bytes
    mock_service.files().get_media.assert_called_once_with(fileId="file_id_123")
