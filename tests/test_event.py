"""Tests for meo-event — fully mocked, no Google credentials needed."""

from unittest.mock import MagicMock, patch
import pytest

from meo.tools.event import (
    run_event,
    _parse_date,
    _parse_time,
    _GBP_POST_TEXT_LIMIT,
    _GBP_EVENT_TITLE_LIMIT,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STORE = {
    "key": "mybear_studio_kyoto",
    "name": "MYBEAR STUDIO 京都店",
    "industry": "fitness",
    "location_id": "accounts/1/locations/3",
}

_STORE_TODO = {
    "key": "mybear_studio_kyoto",
    "name": "MYBEAR STUDIO 京都店",
    "industry": "fitness",
    "location_id": "TODO_location_id",
}

_STORE_EMPTY = {
    "key": "mybear_studio_kyoto",
    "name": "MYBEAR STUDIO 京都店",
    "industry": "fitness",
    "location_id": "",
}

_TITLE = "特別ヨガクラス"
_TEXT = "ゲストインストラクターによる特別クラスを開催します！ぜひご参加ください。"
_POST_NAME = "accounts/1/locations/3/localPosts/42"

_PHOTO_META = {
    "id": "drive_event_photo",
    "name": "yoga_event.jpg",
    "mimeType": "image/jpeg",
    "webContentLink": "https://drive.google.com/uc?id=drive_event_photo",
}
_FAKE_BYTES = b"\xff\xd8\xff"
_GBP_URL = "https://lh3.googleusercontent.com/event/xyz"


def _make_clients():
    gbp = MagicMock()
    gbp.create_event_post.return_value = {"name": _POST_NAME}
    gbp.upload_media_bytes.return_value = _GBP_URL
    drive = MagicMock()
    drive.get_image_metadata.return_value = _PHOTO_META
    drive.download_image.return_value = _FAKE_BYTES
    return gbp, drive


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

def test_parse_date_valid():
    result = _parse_date("2024-10-05")
    assert result == {"year": 2024, "month": 10, "day": 5}


def test_parse_date_single_digit_month():
    result = _parse_date("2024-01-15")
    assert result == {"year": 2024, "month": 1, "day": 15}


def test_parse_date_invalid_format_raises():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _parse_date("05-10-2024")


def test_parse_date_invalid_month_raises():
    with pytest.raises(ValueError):
        _parse_date("2024-13-01")


def test_parse_date_non_date_string_raises():
    with pytest.raises(ValueError):
        _parse_date("next-tuesday")


# ---------------------------------------------------------------------------
# _parse_time
# ---------------------------------------------------------------------------

def test_parse_time_valid_morning():
    result = _parse_time("10:00")
    assert result == {"hours": 10, "minutes": 0}


def test_parse_time_valid_afternoon():
    result = _parse_time("14:30")
    assert result == {"hours": 14, "minutes": 30}


def test_parse_time_midnight():
    result = _parse_time("00:00")
    assert result == {"hours": 0, "minutes": 0}


def test_parse_time_end_of_day():
    result = _parse_time("23:59")
    assert result == {"hours": 23, "minutes": 59}


def test_parse_time_invalid_format_raises():
    with pytest.raises(ValueError, match="HH:MM"):
        _parse_time("10-00")


def test_parse_time_invalid_hour_raises():
    with pytest.raises(ValueError):
        _parse_time("25:00")


def test_parse_time_non_time_string_raises():
    with pytest.raises(ValueError):
        _parse_time("morning")


def test_parse_time_am_pm_raises():
    with pytest.raises(ValueError):
        _parse_time("10:00AM")


# ---------------------------------------------------------------------------
# run_event — dry run
# ---------------------------------------------------------------------------

def test_dry_run_returns_dry_run_status():
    gbp, drive = _make_clients()
    result = run_event(_STORE, _TITLE, _TEXT, gbp, drive, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["store_key"] == "mybear_studio_kyoto"
    assert result["title"] == _TITLE
    assert result["post_text"] == _TEXT


def test_dry_run_makes_no_api_calls():
    gbp, drive = _make_clients()
    run_event(_STORE, _TITLE, _TEXT, gbp, drive, dry_run=True)
    gbp.create_event_post.assert_not_called()
    gbp.upload_media_bytes.assert_not_called()
    drive.download_image.assert_not_called()


def test_dry_run_does_not_write_state():
    gbp, drive = _make_clients()
    with patch("meo.tools.event.record_post") as mock_rp, \
         patch("meo.tools.event.record_post_content") as mock_rpc:
        run_event(_STORE, _TITLE, _TEXT, gbp, drive, dry_run=True)
    mock_rp.assert_not_called()
    mock_rpc.assert_not_called()


def test_dry_run_with_photo_fetches_metadata_not_bytes():
    gbp, drive = _make_clients()
    run_event(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_event_photo", dry_run=True)
    drive.get_image_metadata.assert_called_once_with("drive_event_photo")
    drive.download_image.assert_not_called()
    gbp.upload_media_bytes.assert_not_called()


def test_dry_run_returns_dates_and_times():
    gbp, drive = _make_clients()
    result = run_event(
        _STORE, _TITLE, _TEXT, gbp, drive,
        start_date="2024-10-05", end_date="2024-10-05",
        start_time="10:00", end_time="12:00",
        dry_run=True,
    )
    assert result["start_date"] == "2024-10-05"
    assert result["end_date"] == "2024-10-05"
    assert result["start_time"] == "10:00"
    assert result["end_time"] == "12:00"


def test_dry_run_returns_cta():
    gbp, drive = _make_clients()
    result = run_event(
        _STORE, _TITLE, _TEXT, gbp, drive,
        cta_url="https://example.com/book", cta_action_type="BOOK",
        dry_run=True,
    )
    assert result["call_to_action"] == {"actionType": "BOOK", "url": "https://example.com/book"}


def test_dry_run_no_cta_returns_none():
    gbp, drive = _make_clients()
    result = run_event(_STORE, _TITLE, _TEXT, gbp, drive, dry_run=True)
    assert result["call_to_action"] is None


def test_dry_run_invalid_date_raises_before_dry_run():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run_event(_STORE, _TITLE, _TEXT, gbp, drive, start_date="bad-date", dry_run=True)


def test_dry_run_invalid_time_raises_before_dry_run():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="HH:MM"):
        run_event(_STORE, _TITLE, _TEXT, gbp, drive, start_time="10-00", dry_run=True)


# ---------------------------------------------------------------------------
# run_event — live run, no photo
# ---------------------------------------------------------------------------

def test_live_no_photo_calls_create_event_post():
    gbp, drive = _make_clients()
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        result = run_event(_STORE, _TITLE, _TEXT, gbp, drive)
    gbp.create_event_post.assert_called_once_with(
        _STORE["location_id"], _TITLE, _TEXT,
        start_date=None, end_date=None,
        start_time=None, end_time=None,
        media_url=None, call_to_action=None,
    )
    assert result["status"] == "posted"
    assert result["post_name"] == _POST_NAME


def test_live_with_dates_passes_parsed_dates():
    gbp, drive = _make_clients()
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        run_event(
            _STORE, _TITLE, _TEXT, gbp, drive,
            start_date="2024-10-05", end_date="2024-10-05",
        )
    call_kwargs = gbp.create_event_post.call_args
    assert call_kwargs.kwargs["start_date"] == {"year": 2024, "month": 10, "day": 5}
    assert call_kwargs.kwargs["end_date"] == {"year": 2024, "month": 10, "day": 5}


def test_live_with_times_passes_parsed_times():
    gbp, drive = _make_clients()
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        run_event(
            _STORE, _TITLE, _TEXT, gbp, drive,
            start_time="10:00", end_time="12:30",
        )
    call_kwargs = gbp.create_event_post.call_args
    assert call_kwargs.kwargs["start_time"] == {"hours": 10, "minutes": 0}
    assert call_kwargs.kwargs["end_time"] == {"hours": 12, "minutes": 30}


def test_live_with_all_schedule_fields():
    gbp, drive = _make_clients()
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        run_event(
            _STORE, _TITLE, _TEXT, gbp, drive,
            start_date="2024-10-05", end_date="2024-10-05",
            start_time="10:00", end_time="12:00",
        )
    call_kwargs = gbp.create_event_post.call_args
    assert call_kwargs.kwargs["start_date"] == {"year": 2024, "month": 10, "day": 5}
    assert call_kwargs.kwargs["end_date"] == {"year": 2024, "month": 10, "day": 5}
    assert call_kwargs.kwargs["start_time"] == {"hours": 10, "minutes": 0}
    assert call_kwargs.kwargs["end_time"] == {"hours": 12, "minutes": 0}


def test_live_records_post_and_content():
    gbp, drive = _make_clients()
    with patch("meo.tools.event.record_post") as mock_rp, \
         patch("meo.tools.event.record_post_content") as mock_rpc:
        run_event(_STORE, _TITLE, _TEXT, gbp, drive)
    mock_rp.assert_called_once_with("mybear_studio_kyoto")
    mock_rpc.assert_called_once_with(
        "mybear_studio_kyoto", _TEXT,
        theme=f"EVENT:{_TITLE}", post_name=_POST_NAME, manual=True,
    )


def test_live_with_cta_passes_cta():
    gbp, drive = _make_clients()
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        run_event(
            _STORE, _TITLE, _TEXT, gbp, drive,
            cta_url="https://example.com/book", cta_action_type="BOOK",
        )
    assert gbp.create_event_post.call_args.kwargs["call_to_action"] == {
        "actionType": "BOOK", "url": "https://example.com/book",
    }


def test_live_default_cta_type_is_book():
    gbp, drive = _make_clients()
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        run_event(
            _STORE, _TITLE, _TEXT, gbp, drive,
            cta_url="https://example.com/reserve",
        )
    assert gbp.create_event_post.call_args.kwargs["call_to_action"] == {
        "actionType": "BOOK", "url": "https://example.com/reserve",
    }


def test_live_returns_posted_status():
    gbp, drive = _make_clients()
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        result = run_event(_STORE, _TITLE, _TEXT, gbp, drive)
    assert result["status"] == "posted"
    assert result["title"] == _TITLE


# ---------------------------------------------------------------------------
# run_event — live run, with photo
# ---------------------------------------------------------------------------

def test_live_with_photo_downloads_uploads_and_attaches():
    gbp, drive = _make_clients()
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        run_event(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_event_photo")
    drive.get_image_metadata.assert_called_once_with("drive_event_photo")
    drive.download_image.assert_called_once_with("drive_event_photo")
    gbp.upload_media_bytes.assert_called_once_with(
        _STORE["location_id"], _FAKE_BYTES, "image/jpeg"
    )
    assert gbp.create_event_post.call_args.kwargs["media_url"] == _GBP_URL


def test_live_photo_upload_fails_uses_fallback():
    gbp, drive = _make_clients()
    gbp.upload_media_bytes.side_effect = RuntimeError("GBP upload error")
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        result = run_event(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_event_photo")
    assert gbp.create_event_post.call_args.kwargs["media_url"] == _PHOTO_META["webContentLink"]
    assert result["status"] == "posted"


def test_live_photo_upload_fails_no_fallback_posts_without_photo():
    gbp, drive = _make_clients()
    gbp.upload_media_bytes.side_effect = RuntimeError("GBP upload error")
    drive.get_image_metadata.return_value = {
        "id": "drive_event_photo", "name": "img.jpg", "mimeType": "image/jpeg"
    }
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        result = run_event(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_event_photo")
    assert gbp.create_event_post.call_args.kwargs["media_url"] is None
    assert result["status"] == "posted"


def test_live_photo_download_fails_uses_fallback():
    gbp, drive = _make_clients()
    drive.download_image.side_effect = RuntimeError("network error")
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        result = run_event(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_event_photo")
    gbp.upload_media_bytes.assert_not_called()
    assert gbp.create_event_post.call_args.kwargs["media_url"] == _PHOTO_META["webContentLink"]
    assert result["status"] == "posted"


def test_live_photo_metadata_fails_posts_without_photo():
    gbp, drive = _make_clients()
    drive.get_image_metadata.side_effect = RuntimeError("permission denied")
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"):
        result = run_event(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_event_photo")
    drive.download_image.assert_not_called()
    assert gbp.create_event_post.call_args.kwargs["media_url"] is None
    assert result["status"] == "posted"


# ---------------------------------------------------------------------------
# run_event — validation
# ---------------------------------------------------------------------------

def test_raises_on_todo_location_id():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="location_id is not configured"):
        run_event(_STORE_TODO, _TITLE, _TEXT, gbp, drive)


def test_raises_on_empty_location_id():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="location_id is not configured"):
        run_event(_STORE_EMPTY, _TITLE, _TEXT, gbp, drive)


def test_raises_on_invalid_start_date():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run_event(_STORE, _TITLE, _TEXT, gbp, drive, start_date="bad-date")


def test_raises_on_invalid_end_date():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run_event(_STORE, _TITLE, _TEXT, gbp, drive, end_date="2024/10/05")


def test_raises_on_invalid_start_time():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="HH:MM"):
        run_event(_STORE, _TITLE, _TEXT, gbp, drive, start_time="bad-time")


def test_raises_on_invalid_end_time():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="HH:MM"):
        run_event(_STORE, _TITLE, _TEXT, gbp, drive, end_time="25:00")


# ---------------------------------------------------------------------------
# run_event — warning thresholds
# ---------------------------------------------------------------------------

def test_long_title_logs_warning(caplog):
    gbp, drive = _make_clients()
    long_title = "あ" * (_GBP_EVENT_TITLE_LIMIT + 1)
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"), \
         caplog.at_level("WARNING"):
        result = run_event(_STORE, long_title, _TEXT, gbp, drive)
    assert result["status"] == "posted"
    assert any("title" in r.message.lower() or "truncate" in r.message.lower() for r in caplog.records)


def test_title_at_limit_no_warning(caplog):
    gbp, drive = _make_clients()
    ok_title = "あ" * _GBP_EVENT_TITLE_LIMIT
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"), \
         caplog.at_level("WARNING"):
        run_event(_STORE, ok_title, _TEXT, gbp, drive)
    title_warnings = [r for r in caplog.records if "title" in r.message.lower() and r.levelname == "WARNING"]
    assert not title_warnings


def test_long_text_logs_warning(caplog):
    gbp, drive = _make_clients()
    long_text = "あ" * (_GBP_POST_TEXT_LIMIT + 1)
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"), \
         caplog.at_level("WARNING"):
        result = run_event(_STORE, _TITLE, long_text, gbp, drive)
    assert result["status"] == "posted"
    assert any("chars" in r.message.lower() or "limit" in r.message.lower() for r in caplog.records)


def test_text_at_limit_no_warning(caplog):
    gbp, drive = _make_clients()
    ok_text = "あ" * _GBP_POST_TEXT_LIMIT
    with patch("meo.tools.event.record_post"), \
         patch("meo.tools.event.record_post_content"), \
         caplog.at_level("WARNING"):
        run_event(_STORE, _TITLE, ok_text, gbp, drive)
    text_warnings = [
        r for r in caplog.records
        if ("chars" in r.message.lower() or "limit" in r.message.lower()) and r.levelname == "WARNING"
    ]
    assert not text_warnings


# ---------------------------------------------------------------------------
# create_event_post — BusinessProfileClient
# ---------------------------------------------------------------------------

def test_business_profile_create_event_post_minimal():
    """create_event_post with only required args sends correct API body."""
    from unittest.mock import MagicMock, patch as p
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"name": "accounts/1/locations/3/localPosts/1"}

    client = BusinessProfileClient(creds)
    with p.object(client._session, "post", return_value=mock_resp) as mp:
        client.create_event_post(
            "accounts/1/locations/3",
            "特別クラス",
            "本文テキスト",
        )
        body = mp.call_args.kwargs.get("json") or mp.call_args[1].get("json")

    assert body["topicType"] == "EVENT"
    assert body["languageCode"] == "ja"
    assert body["summary"] == "本文テキスト"
    assert body["event"]["title"] == "特別クラス"
    assert "schedule" not in body["event"]
    assert "offer" not in body


def test_business_profile_create_event_post_with_dates_only():
    """create_event_post with dates but no times sets only date fields in schedule."""
    from unittest.mock import MagicMock, patch as p
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"name": "accounts/1/locations/3/localPosts/2"}

    start = {"year": 2024, "month": 10, "day": 5}
    end = {"year": 2024, "month": 10, "day": 6}

    client = BusinessProfileClient(creds)
    with p.object(client._session, "post", return_value=mock_resp) as mp:
        client.create_event_post(
            "accounts/1/locations/3",
            "週末イベント",
            "内容",
            start_date=start,
            end_date=end,
        )
        body = mp.call_args.kwargs.get("json") or mp.call_args[1].get("json")

    assert body["topicType"] == "EVENT"
    assert body["event"]["schedule"]["startDate"] == start
    assert body["event"]["schedule"]["endDate"] == end
    assert "startTime" not in body["event"]["schedule"]
    assert "endTime" not in body["event"]["schedule"]


def test_business_profile_create_event_post_full():
    """create_event_post with all optional fields sends them all."""
    from unittest.mock import MagicMock, patch as p
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"name": "accounts/1/locations/3/localPosts/3"}

    start_date = {"year": 2024, "month": 10, "day": 5}
    end_date = {"year": 2024, "month": 10, "day": 5}
    start_time = {"hours": 10, "minutes": 0}
    end_time = {"hours": 12, "minutes": 30}

    client = BusinessProfileClient(creds)
    with p.object(client._session, "post", return_value=mock_resp) as mp:
        client.create_event_post(
            "accounts/1/locations/3",
            "特別ヨガクラス",
            "ゲスト講師によるクラスです。",
            start_date=start_date,
            end_date=end_date,
            start_time=start_time,
            end_time=end_time,
            media_url="https://lh3.example.com/event.jpg",
            call_to_action={"actionType": "BOOK", "url": "https://example.com/book"},
        )
        body = mp.call_args.kwargs.get("json") or mp.call_args[1].get("json")

    assert body["topicType"] == "EVENT"
    assert body["event"]["title"] == "特別ヨガクラス"
    assert body["event"]["schedule"]["startDate"] == start_date
    assert body["event"]["schedule"]["endDate"] == end_date
    assert body["event"]["schedule"]["startTime"] == start_time
    assert body["event"]["schedule"]["endTime"] == end_time
    assert body["media"] == [{"mediaFormat": "PHOTO", "sourceUrl": "https://lh3.example.com/event.jpg"}]
    assert body["callToAction"] == {"actionType": "BOOK", "url": "https://example.com/book"}
    assert "offer" not in body


def test_business_profile_create_event_post_time_only_no_date():
    """create_event_post with time but no date still populates schedule with time only."""
    from unittest.mock import MagicMock, patch as p
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"name": "accounts/1/locations/3/localPosts/4"}

    start_time = {"hours": 9, "minutes": 30}

    client = BusinessProfileClient(creds)
    with p.object(client._session, "post", return_value=mock_resp) as mp:
        client.create_event_post(
            "accounts/1/locations/3",
            "朝ヨガ",
            "朝の特別クラス",
            start_time=start_time,
        )
        body = mp.call_args.kwargs.get("json") or mp.call_args[1].get("json")

    assert body["event"]["schedule"]["startTime"] == start_time
    assert "startDate" not in body["event"]["schedule"]
