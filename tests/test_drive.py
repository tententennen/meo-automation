"""Tests for DriveClient — mocked googleapiclient so no credentials are needed."""

from unittest.mock import MagicMock, patch
import pytest

from meo.drive import DriveClient


def _make_file(file_id: str, name: str, mime: str = "image/jpeg", size: str | None = None) -> dict:
    f: dict = {
        "id": file_id,
        "name": name,
        "mimeType": mime,
        "webContentLink": f"https://drive.google.com/uc?id={file_id}",
    }
    if size is not None:
        f["size"] = size
    return f


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


# ---------------------------------------------------------------------------
# get_image_metadata
# ---------------------------------------------------------------------------

def test_get_image_metadata_calls_files_get(client, mock_service):
    expected = {
        "id": "file_abc",
        "name": "photo.jpg",
        "mimeType": "image/jpeg",
        "webContentLink": "https://drive.google.com/uc?id=file_abc",
    }
    mock_service.files().get.return_value.execute.return_value = expected

    result = client.get_image_metadata("file_abc")

    mock_service.files().get.assert_called_once_with(
        fileId="file_abc",
        fields="id, name, mimeType, webContentLink",
    )
    assert result == expected


def test_get_image_metadata_propagates_http_error(client, mock_service):
    mock_service.files().get.return_value.execute.side_effect = RuntimeError("404 not found")
    with pytest.raises(RuntimeError, match="404"):
        client.get_image_metadata("nonexistent_file")


# ---------------------------------------------------------------------------
# list_images — size field included in API fields string
# ---------------------------------------------------------------------------

def test_list_images_requests_size_field(client, mock_service):
    """list_images must include 'size' in the Drive API fields parameter."""
    mock_service.files().list().execute.return_value = {"files": []}
    client.list_images("folder_id")
    call_kwargs = mock_service.files().list.call_args.kwargs
    assert "size" in call_kwargs.get("fields", ""), (
        f"Expected 'size' in Drive fields string; got: {call_kwargs.get('fields')}"
    )


# ---------------------------------------------------------------------------
# pick_random_image — max_bytes size filter
# ---------------------------------------------------------------------------

def test_pick_random_image_size_filter_excludes_oversized(client, mock_service):
    """Images exceeding max_bytes are excluded; a smaller image is picked."""
    mock_service.files().list().execute.return_value = {
        "files": [
            _make_file("small", "small.jpg", size="1000"),
            _make_file("large", "large.jpg", size="10000000"),
        ],
    }
    result = client.pick_random_image("folder_id", max_bytes=5_000_000)
    assert result is not None
    assert result["id"] == "small"


def test_pick_random_image_all_oversized_returns_none(client, mock_service):
    """When every image exceeds max_bytes, pick_random_image returns None."""
    mock_service.files().list().execute.return_value = {
        "files": [_make_file("big", "big.jpg", size="9999999")],
    }
    result = client.pick_random_image("folder_id", max_bytes=5_000_000)
    assert result is None


def test_pick_random_image_all_oversized_logs_warning(client, mock_service, caplog):
    """When all images are oversized, a WARNING is logged describing the situation."""
    import logging
    mock_service.files().list().execute.return_value = {
        "files": [_make_file("big", "big.jpg", size="9999999")],
    }
    with caplog.at_level(logging.WARNING, logger="meo.drive"):
        client.pick_random_image("folder_id", max_bytes=5_000_000)
    assert any("size limit" in r.message for r in caplog.records if r.levelno >= logging.WARNING)


def test_pick_random_image_missing_size_field_is_included(client, mock_service):
    """Images with no 'size' field are treated as 0 bytes and always included."""
    mock_service.files().list().execute.return_value = {
        "files": [_make_file("no_size", "photo.jpg")],  # no size key
    }
    result = client.pick_random_image("folder_id", max_bytes=1)
    assert result is not None
    assert result["id"] == "no_size"


def test_pick_random_image_exact_limit_is_included(client, mock_service):
    """An image whose size exactly equals max_bytes is included (boundary is inclusive)."""
    mock_service.files().list().execute.return_value = {
        "files": [_make_file("edge", "edge.jpg", size="5242880")],
    }
    result = client.pick_random_image("folder_id", max_bytes=5_242_880)
    assert result is not None
    assert result["id"] == "edge"


def test_pick_random_image_size_filter_then_recent_ids_filter(client, mock_service):
    """Size filtering applies before recent-ids filtering; fresh valid image is preferred."""
    mock_service.files().list().execute.return_value = {
        "files": [
            _make_file("used_small", "used.jpg", size="1000"),
            _make_file("fresh_small", "fresh.jpg", size="2000"),
            _make_file("oversized", "big.jpg", size="9999999"),
        ],
    }
    result = client.pick_random_image(
        "folder_id", recent_ids=["used_small"], max_bytes=5_000_000
    )
    assert result is not None
    assert result["id"] == "fresh_small"


def test_pick_random_image_no_max_bytes_does_not_filter(client, mock_service):
    """When max_bytes is None (default), size is not checked and all images are eligible."""
    mock_service.files().list().execute.return_value = {
        "files": [_make_file("huge", "huge.jpg", size="999999999")],
    }
    result = client.pick_random_image("folder_id")  # no max_bytes
    assert result is not None
    assert result["id"] == "huge"
