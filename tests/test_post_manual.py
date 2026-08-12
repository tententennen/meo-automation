"""Tests for meo-post-manual — fully mocked, no Google credentials needed."""

from unittest.mock import MagicMock, patch, call
import pytest

from meo.tools.post_manual import run_post_manual, _GBP_POST_TEXT_LIMIT


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STORE = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
    "location_id": "accounts/1/locations/2",
}

_STORE_UNCONFIGURED = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
    "location_id": "TODO_location_id",
}

_STORE_MISSING_LOCATION = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
    "location_id": "",
}

_PHOTO_META = {
    "id": "drive_file_abc",
    "name": "interior.jpg",
    "mimeType": "image/jpeg",
    "webContentLink": "https://drive.google.com/uc?id=drive_file_abc",
}
_FAKE_BYTES = b"\xff\xd8\xff"
_GBP_URL = "https://lh3.googleusercontent.com/hosted/abc"
_POST_NAME = "accounts/1/locations/2/localPosts/777"
_TEXT = "特別セールのお知らせです。ぜひご来店ください！"


def _make_clients():
    gbp = MagicMock()
    gbp.create_local_post.return_value = {"name": _POST_NAME}
    gbp.upload_media_bytes.return_value = _GBP_URL
    drive = MagicMock()
    drive.get_image_metadata.return_value = _PHOTO_META
    drive.download_image.return_value = _FAKE_BYTES
    return gbp, drive


# ---------------------------------------------------------------------------
# run_post_manual — dry run
# ---------------------------------------------------------------------------

def test_dry_run_no_photo_returns_dry_run_status():
    gbp, drive = _make_clients()
    result = run_post_manual(_STORE, _TEXT, gbp, drive, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["store_key"] == "the_body_kyoto"
    assert result["post_text"] == _TEXT
    assert result["photo_file_id"] is None
    gbp.create_local_post.assert_not_called()
    drive.get_image_metadata.assert_not_called()


def test_dry_run_no_photo_does_not_write_state():
    gbp, drive = _make_clients()
    with patch("meo.tools.post_manual.record_post") as mock_rp, \
         patch("meo.tools.post_manual.record_post_content") as mock_rpc:
        run_post_manual(_STORE, _TEXT, gbp, drive, dry_run=True)
    mock_rp.assert_not_called()
    mock_rpc.assert_not_called()


def test_dry_run_with_photo_fetches_metadata_but_does_not_download():
    gbp, drive = _make_clients()
    result = run_post_manual(
        _STORE, _TEXT, gbp, drive, photo_file_id="drive_file_abc", dry_run=True
    )
    drive.get_image_metadata.assert_called_once_with("drive_file_abc")
    drive.download_image.assert_not_called()
    gbp.upload_media_bytes.assert_not_called()
    gbp.create_local_post.assert_not_called()
    assert result["photo_file_id"] == "drive_file_abc"
    assert result["status"] == "dry_run"


def test_dry_run_with_cta_returns_cta_in_result():
    gbp, drive = _make_clients()
    result = run_post_manual(
        _STORE, _TEXT, gbp, drive,
        cta_url="https://example.com/book",
        cta_action_type="BOOK",
        dry_run=True,
    )
    assert result["call_to_action"] == {"actionType": "BOOK", "url": "https://example.com/book"}


def test_dry_run_no_cta_has_none_call_to_action():
    gbp, drive = _make_clients()
    result = run_post_manual(_STORE, _TEXT, gbp, drive, dry_run=True)
    assert result["call_to_action"] is None


# ---------------------------------------------------------------------------
# run_post_manual — live run, no photo
# ---------------------------------------------------------------------------

def test_live_no_photo_calls_create_local_post():
    gbp, drive = _make_clients()
    with patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"):
        result = run_post_manual(_STORE, _TEXT, gbp, drive, dry_run=False)
    gbp.create_local_post.assert_called_once_with(
        _STORE["location_id"], _TEXT, None, call_to_action=None
    )
    assert result["status"] == "posted"
    assert result["post_name"] == _POST_NAME


def test_live_no_photo_records_post_and_content():
    gbp, drive = _make_clients()
    with patch("meo.tools.post_manual.record_post") as mock_rp, \
         patch("meo.tools.post_manual.record_post_content") as mock_rpc:
        run_post_manual(_STORE, _TEXT, gbp, drive, dry_run=False)
    mock_rp.assert_called_once_with("the_body_kyoto")
    mock_rpc.assert_called_once_with(
        "the_body_kyoto", _TEXT, theme=None, post_name=_POST_NAME, manual=True
    )


def test_live_with_cta_passes_cta_to_create():
    gbp, drive = _make_clients()
    with patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"):
        run_post_manual(
            _STORE, _TEXT, gbp, drive,
            cta_url="https://example.com",
            cta_action_type="LEARN_MORE",
            dry_run=False,
        )
    gbp.create_local_post.assert_called_once_with(
        _STORE["location_id"], _TEXT, None,
        call_to_action={"actionType": "LEARN_MORE", "url": "https://example.com"},
    )


# ---------------------------------------------------------------------------
# run_post_manual — live run, with photo
# ---------------------------------------------------------------------------

def test_live_with_photo_downloads_uploads_and_attaches():
    gbp, drive = _make_clients()
    with patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"):
        result = run_post_manual(
            _STORE, _TEXT, gbp, drive, photo_file_id="drive_file_abc", dry_run=False
        )
    drive.get_image_metadata.assert_called_once_with("drive_file_abc")
    drive.download_image.assert_called_once_with("drive_file_abc")
    gbp.upload_media_bytes.assert_called_once_with(
        _STORE["location_id"], _FAKE_BYTES, "image/jpeg"
    )
    gbp.create_local_post.assert_called_once_with(
        _STORE["location_id"], _TEXT, _GBP_URL, call_to_action=None
    )
    assert result["status"] == "posted"


def test_live_photo_upload_fails_uses_fallback_url():
    gbp, drive = _make_clients()
    gbp.upload_media_bytes.side_effect = RuntimeError("GBP upload failed")
    with patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"):
        result = run_post_manual(
            _STORE, _TEXT, gbp, drive, photo_file_id="drive_file_abc", dry_run=False
        )
    # Should fall back to webContentLink
    gbp.create_local_post.assert_called_once_with(
        _STORE["location_id"], _TEXT, _PHOTO_META["webContentLink"], call_to_action=None
    )
    assert result["status"] == "posted"


def test_live_photo_upload_fails_no_fallback_posts_without_photo():
    gbp, drive = _make_clients()
    gbp.upload_media_bytes.side_effect = RuntimeError("GBP upload failed")
    drive.get_image_metadata.return_value = {
        "id": "drive_file_abc",
        "name": "interior.jpg",
        "mimeType": "image/jpeg",
        # no webContentLink key
    }
    with patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"):
        result = run_post_manual(
            _STORE, _TEXT, gbp, drive, photo_file_id="drive_file_abc", dry_run=False
        )
    gbp.create_local_post.assert_called_once_with(
        _STORE["location_id"], _TEXT, None, call_to_action=None
    )
    assert result["status"] == "posted"


def test_live_photo_download_fails_uses_fallback_url(caplog):
    """When download fails but webContentLink is present, it is used as fallback."""
    gbp, drive = _make_clients()
    drive.download_image.side_effect = RuntimeError("network error")
    with patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"):
        result = run_post_manual(
            _STORE, _TEXT, gbp, drive, photo_file_id="drive_file_abc", dry_run=False
        )
    gbp.upload_media_bytes.assert_not_called()
    gbp.create_local_post.assert_called_once_with(
        _STORE["location_id"], _TEXT, _PHOTO_META["webContentLink"], call_to_action=None
    )
    assert result["status"] == "posted"


def test_live_photo_download_fails_no_fallback_posts_without_photo(caplog):
    """When download fails and there is no webContentLink, the post goes out without photo."""
    gbp, drive = _make_clients()
    drive.download_image.side_effect = RuntimeError("network error")
    drive.get_image_metadata.return_value = {
        "id": "drive_file_abc",
        "name": "interior.jpg",
        "mimeType": "image/jpeg",
        # no webContentLink
    }
    with patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"):
        result = run_post_manual(
            _STORE, _TEXT, gbp, drive, photo_file_id="drive_file_abc", dry_run=False
        )
    gbp.upload_media_bytes.assert_not_called()
    gbp.create_local_post.assert_called_once_with(
        _STORE["location_id"], _TEXT, None, call_to_action=None
    )
    assert result["status"] == "posted"


def test_live_photo_metadata_fails_posts_without_photo(caplog):
    gbp, drive = _make_clients()
    drive.get_image_metadata.side_effect = RuntimeError("permission denied")
    with patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"):
        result = run_post_manual(
            _STORE, _TEXT, gbp, drive, photo_file_id="drive_file_abc", dry_run=False
        )
    drive.download_image.assert_not_called()
    gbp.create_local_post.assert_called_once_with(
        _STORE["location_id"], _TEXT, None, call_to_action=None
    )
    assert result["status"] == "posted"


# ---------------------------------------------------------------------------
# run_post_manual — location_id validation
# ---------------------------------------------------------------------------

def test_raises_on_todo_location_id():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="location_id is not configured"):
        run_post_manual(_STORE_UNCONFIGURED, _TEXT, gbp, drive)


def test_raises_on_empty_location_id():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="location_id is not configured"):
        run_post_manual(_STORE_MISSING_LOCATION, _TEXT, gbp, drive)


# ---------------------------------------------------------------------------
# run_post_manual — text length warning
# ---------------------------------------------------------------------------

def test_text_too_long_logs_warning_but_still_posts(caplog):
    gbp, drive = _make_clients()
    long_text = "あ" * (_GBP_POST_TEXT_LIMIT + 1)
    with patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"), \
         caplog.at_level("WARNING"):
        result = run_post_manual(_STORE, long_text, gbp, drive, dry_run=False)
    assert result["status"] == "posted"
    assert any("limit" in r.message.lower() or "chars" in r.message.lower() for r in caplog.records)


def test_text_at_limit_does_not_warn(caplog):
    gbp, drive = _make_clients()
    ok_text = "あ" * _GBP_POST_TEXT_LIMIT
    with patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"), \
         caplog.at_level("WARNING"):
        run_post_manual(_STORE, ok_text, gbp, drive, dry_run=False)
    length_warnings = [
        r for r in caplog.records
        if "limit" in r.message.lower() or "chars" in r.message.lower()
    ]
    assert not length_warnings


# ---------------------------------------------------------------------------
# main() — CLI argument parsing and exit codes
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_store_list():
    return [
        {
            "key": "the_body_kyoto",
            "name": "THE BODY 京都店",
            "industry": "beauty_salon",
            "location_id": "accounts/1/locations/2",
        }
    ]


def test_main_unknown_store_exits_1(mock_store_list, capsys):
    with patch("meo.tools.post_manual.cfg.store_list", return_value=mock_store_list):
        with pytest.raises(SystemExit) as exc_info:
            import sys
            sys.argv = ["meo-post-manual", "--store", "nonexistent_store", "--text", "hello"]
            from meo.tools.post_manual import main
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Unknown store key" in captured.err


def test_main_auth_failure_exits_1(mock_store_list, capsys):
    with patch("meo.tools.post_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.post_manual.get_credentials", side_effect=RuntimeError("no creds")):
        with pytest.raises(SystemExit) as exc_info:
            import sys
            sys.argv = ["meo-post-manual", "--store", "the_body_kyoto", "--text", "hello"]
            from meo.tools.post_manual import main
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Authentication failed" in captured.err


def test_main_value_error_exits_1(mock_store_list, capsys):
    unconfigured = [{**mock_store_list[0], "location_id": "TODO_location_id"}]
    with patch("meo.tools.post_manual.cfg.store_list", return_value=unconfigured), \
         patch("meo.tools.post_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.post_manual.BusinessProfileClient"), \
         patch("meo.tools.post_manual.DriveClient"):
        with pytest.raises(SystemExit) as exc_info:
            import sys
            sys.argv = ["meo-post-manual", "--store", "the_body_kyoto", "--text", "hello"]
            from meo.tools.post_manual import main
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Error:" in captured.err


def test_main_dry_run_prints_dry_run_prefix(mock_store_list, capsys):
    with patch("meo.tools.post_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.post_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.post_manual.BusinessProfileClient") as MockGBP, \
         patch("meo.tools.post_manual.DriveClient") as MockDrive:
        MockGBP.return_value.create_local_post.return_value = {"name": _POST_NAME}
        MockDrive.return_value.get_image_metadata.return_value = _PHOTO_META
        import sys
        sys.argv = [
            "meo-post-manual", "--store", "the_body_kyoto",
            "--text", _TEXT, "--dry-run",
        ]
        from meo.tools.post_manual import main
        main()
    captured = capsys.readouterr()
    assert "[DRY RUN]" in captured.out


def test_main_live_prints_post_name(mock_store_list, capsys):
    with patch("meo.tools.post_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.post_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.post_manual.BusinessProfileClient") as MockGBP, \
         patch("meo.tools.post_manual.DriveClient") as MockDrive, \
         patch("meo.tools.post_manual.record_post"), \
         patch("meo.tools.post_manual.record_post_content"):
        MockGBP.return_value.create_local_post.return_value = {"name": _POST_NAME}
        MockDrive.return_value.get_image_metadata.return_value = _PHOTO_META
        import sys
        sys.argv = [
            "meo-post-manual", "--store", "the_body_kyoto", "--text", _TEXT,
        ]
        from meo.tools.post_manual import main
        main()
    captured = capsys.readouterr()
    assert "[DRY RUN]" not in captured.out
    assert _POST_NAME in captured.out


def test_main_unexpected_error_exits_1(mock_store_list, capsys):
    with patch("meo.tools.post_manual.cfg.store_list", return_value=mock_store_list), \
         patch("meo.tools.post_manual.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.post_manual.BusinessProfileClient") as MockGBP, \
         patch("meo.tools.post_manual.DriveClient"):
        MockGBP.return_value.create_local_post.side_effect = RuntimeError("network error")
        with pytest.raises(SystemExit) as exc_info:
            import sys
            sys.argv = [
                "meo-post-manual", "--store", "the_body_kyoto", "--text", _TEXT,
            ]
            from meo.tools.post_manual import main
            main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "Unexpected error" in captured.err
