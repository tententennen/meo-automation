"""Tests for meo-offer — fully mocked, no Google credentials needed."""

from unittest.mock import MagicMock, patch
import pytest

from meo.tools.offer import (
    run_offer,
    _parse_date,
    _GBP_POST_TEXT_LIMIT,
    _GBP_OFFER_TITLE_LIMIT,
)


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STORE = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
    "location_id": "accounts/1/locations/2",
}

_STORE_TODO = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
    "location_id": "TODO_location_id",
}

_STORE_EMPTY = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "industry": "beauty_salon",
    "location_id": "",
}

_TITLE = "夏の特別キャンペーン"
_TEXT = "今月限定！全メニュー20%オフです。ぜひご来店ください。"
_POST_NAME = "accounts/1/locations/2/localPosts/999"

_PHOTO_META = {
    "id": "drive_photo_abc",
    "name": "summer.jpg",
    "mimeType": "image/jpeg",
    "webContentLink": "https://drive.google.com/uc?id=drive_photo_abc",
}
_FAKE_BYTES = b"\xff\xd8\xff"
_GBP_URL = "https://lh3.googleusercontent.com/offer/abc"


def _make_clients():
    gbp = MagicMock()
    gbp.create_offer_post.return_value = {"name": _POST_NAME}
    gbp.upload_media_bytes.return_value = _GBP_URL
    drive = MagicMock()
    drive.get_image_metadata.return_value = _PHOTO_META
    drive.download_image.return_value = _FAKE_BYTES
    return gbp, drive


# ---------------------------------------------------------------------------
# _parse_date
# ---------------------------------------------------------------------------

def test_parse_date_valid():
    result = _parse_date("2024-08-01")
    assert result == {"year": 2024, "month": 8, "day": 1}


def test_parse_date_valid_end_of_month():
    result = _parse_date("2024-08-31")
    assert result == {"year": 2024, "month": 8, "day": 31}


def test_parse_date_invalid_format_raises():
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        _parse_date("01-08-2024")


def test_parse_date_invalid_month_raises():
    with pytest.raises(ValueError):
        _parse_date("2024-13-01")


def test_parse_date_non_date_string_raises():
    with pytest.raises(ValueError):
        _parse_date("not-a-date")


# ---------------------------------------------------------------------------
# run_offer — dry run
# ---------------------------------------------------------------------------

def test_dry_run_returns_dry_run_status():
    gbp, drive = _make_clients()
    result = run_offer(_STORE, _TITLE, _TEXT, gbp, drive, dry_run=True)
    assert result["status"] == "dry_run"
    assert result["store_key"] == "the_body_kyoto"
    assert result["title"] == _TITLE
    assert result["post_text"] == _TEXT


def test_dry_run_makes_no_api_calls():
    gbp, drive = _make_clients()
    run_offer(_STORE, _TITLE, _TEXT, gbp, drive, dry_run=True)
    gbp.create_offer_post.assert_not_called()
    gbp.upload_media_bytes.assert_not_called()
    drive.download_image.assert_not_called()


def test_dry_run_does_not_write_state():
    gbp, drive = _make_clients()
    with patch("meo.tools.offer.record_post") as mock_rp, \
         patch("meo.tools.offer.record_post_content") as mock_rpc:
        run_offer(_STORE, _TITLE, _TEXT, gbp, drive, dry_run=True)
    mock_rp.assert_not_called()
    mock_rpc.assert_not_called()


def test_dry_run_with_photo_fetches_metadata_not_bytes():
    gbp, drive = _make_clients()
    run_offer(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_photo_abc", dry_run=True)
    drive.get_image_metadata.assert_called_once_with("drive_photo_abc")
    drive.download_image.assert_not_called()
    gbp.upload_media_bytes.assert_not_called()


def test_dry_run_returns_dates_and_coupon():
    gbp, drive = _make_clients()
    result = run_offer(
        _STORE, _TITLE, _TEXT, gbp, drive,
        start_date="2024-08-01", end_date="2024-08-31",
        coupon_code="SUMMER20",
        dry_run=True,
    )
    assert result["start_date"] == "2024-08-01"
    assert result["end_date"] == "2024-08-31"
    assert result["coupon_code"] == "SUMMER20"


def test_dry_run_returns_cta():
    gbp, drive = _make_clients()
    result = run_offer(
        _STORE, _TITLE, _TEXT, gbp, drive,
        cta_url="https://example.com/book", cta_action_type="BOOK",
        dry_run=True,
    )
    assert result["call_to_action"] == {"actionType": "BOOK", "url": "https://example.com/book"}


def test_dry_run_no_cta_returns_none():
    gbp, drive = _make_clients()
    result = run_offer(_STORE, _TITLE, _TEXT, gbp, drive, dry_run=True)
    assert result["call_to_action"] is None


def test_dry_run_invalid_date_raises_before_dry_run():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run_offer(_STORE, _TITLE, _TEXT, gbp, drive, start_date="not-a-date", dry_run=True)


# ---------------------------------------------------------------------------
# run_offer — live run, no photo
# ---------------------------------------------------------------------------

def test_live_no_photo_calls_create_offer_post():
    gbp, drive = _make_clients()
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"):
        result = run_offer(_STORE, _TITLE, _TEXT, gbp, drive)
    gbp.create_offer_post.assert_called_once_with(
        _STORE["location_id"], _TITLE, _TEXT,
        start_date=None, end_date=None,
        coupon_code=None, redeem_url=None, terms=None,
        media_url=None, call_to_action=None,
    )
    assert result["status"] == "posted"
    assert result["post_name"] == _POST_NAME


def test_live_with_dates_passes_parsed_dates():
    gbp, drive = _make_clients()
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"):
        run_offer(
            _STORE, _TITLE, _TEXT, gbp, drive,
            start_date="2024-08-01", end_date="2024-08-31",
        )
    call_kwargs = gbp.create_offer_post.call_args
    assert call_kwargs.kwargs["start_date"] == {"year": 2024, "month": 8, "day": 1}
    assert call_kwargs.kwargs["end_date"] == {"year": 2024, "month": 8, "day": 31}


def test_live_with_coupon_passes_coupon():
    gbp, drive = _make_clients()
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"):
        run_offer(
            _STORE, _TITLE, _TEXT, gbp, drive,
            coupon_code="SUMMER20",
        )
    assert gbp.create_offer_post.call_args.kwargs["coupon_code"] == "SUMMER20"


def test_live_with_redeem_url_and_terms():
    gbp, drive = _make_clients()
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"):
        run_offer(
            _STORE, _TITLE, _TEXT, gbp, drive,
            redeem_url="https://example.com/book",
            terms="ご新規様限定。",
        )
    kwargs = gbp.create_offer_post.call_args.kwargs
    assert kwargs["redeem_url"] == "https://example.com/book"
    assert kwargs["terms"] == "ご新規様限定。"


def test_live_records_post_and_content():
    gbp, drive = _make_clients()
    with patch("meo.tools.offer.record_post") as mock_rp, \
         patch("meo.tools.offer.record_post_content") as mock_rpc:
        run_offer(_STORE, _TITLE, _TEXT, gbp, drive)
    mock_rp.assert_called_once_with("the_body_kyoto")
    mock_rpc.assert_called_once_with(
        "the_body_kyoto", _TEXT,
        theme=f"OFFER:{_TITLE}", post_name=_POST_NAME, manual=True,
    )


def test_live_with_cta_passes_cta():
    gbp, drive = _make_clients()
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"):
        run_offer(
            _STORE, _TITLE, _TEXT, gbp, drive,
            cta_url="https://example.com", cta_action_type="BOOK",
        )
    assert gbp.create_offer_post.call_args.kwargs["call_to_action"] == {
        "actionType": "BOOK", "url": "https://example.com",
    }


# ---------------------------------------------------------------------------
# run_offer — live run, with photo
# ---------------------------------------------------------------------------

def test_live_with_photo_downloads_uploads_and_attaches():
    gbp, drive = _make_clients()
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"):
        run_offer(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_photo_abc")
    drive.get_image_metadata.assert_called_once_with("drive_photo_abc")
    drive.download_image.assert_called_once_with("drive_photo_abc")
    gbp.upload_media_bytes.assert_called_once_with(
        _STORE["location_id"], _FAKE_BYTES, "image/jpeg"
    )
    assert gbp.create_offer_post.call_args.kwargs["media_url"] == _GBP_URL


def test_live_photo_upload_fails_uses_fallback():
    gbp, drive = _make_clients()
    gbp.upload_media_bytes.side_effect = RuntimeError("GBP upload error")
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"):
        result = run_offer(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_photo_abc")
    assert gbp.create_offer_post.call_args.kwargs["media_url"] == _PHOTO_META["webContentLink"]
    assert result["status"] == "posted"


def test_live_photo_upload_fails_no_fallback_posts_without_photo():
    gbp, drive = _make_clients()
    gbp.upload_media_bytes.side_effect = RuntimeError("GBP upload error")
    drive.get_image_metadata.return_value = {
        "id": "drive_photo_abc", "name": "img.jpg", "mimeType": "image/jpeg"
    }
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"):
        result = run_offer(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_photo_abc")
    assert gbp.create_offer_post.call_args.kwargs["media_url"] is None
    assert result["status"] == "posted"


def test_live_photo_download_fails_uses_fallback():
    gbp, drive = _make_clients()
    drive.download_image.side_effect = RuntimeError("network error")
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"):
        result = run_offer(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_photo_abc")
    gbp.upload_media_bytes.assert_not_called()
    assert gbp.create_offer_post.call_args.kwargs["media_url"] == _PHOTO_META["webContentLink"]
    assert result["status"] == "posted"


def test_live_photo_metadata_fails_posts_without_photo():
    gbp, drive = _make_clients()
    drive.get_image_metadata.side_effect = RuntimeError("permission denied")
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"):
        result = run_offer(_STORE, _TITLE, _TEXT, gbp, drive, photo_file_id="drive_photo_abc")
    drive.download_image.assert_not_called()
    assert gbp.create_offer_post.call_args.kwargs["media_url"] is None
    assert result["status"] == "posted"


# ---------------------------------------------------------------------------
# run_offer — validation
# ---------------------------------------------------------------------------

def test_raises_on_todo_location_id():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="location_id is not configured"):
        run_offer(_STORE_TODO, _TITLE, _TEXT, gbp, drive)


def test_raises_on_empty_location_id():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="location_id is not configured"):
        run_offer(_STORE_EMPTY, _TITLE, _TEXT, gbp, drive)


def test_raises_on_invalid_start_date():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run_offer(_STORE, _TITLE, _TEXT, gbp, drive, start_date="bad-date")


def test_raises_on_invalid_end_date():
    gbp, drive = _make_clients()
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        run_offer(_STORE, _TITLE, _TEXT, gbp, drive, end_date="2024/08/31")


# ---------------------------------------------------------------------------
# run_offer — warning thresholds
# ---------------------------------------------------------------------------

def test_long_title_logs_warning(caplog):
    gbp, drive = _make_clients()
    long_title = "あ" * (_GBP_OFFER_TITLE_LIMIT + 1)
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"), \
         caplog.at_level("WARNING"):
        result = run_offer(_STORE, long_title, _TEXT, gbp, drive)
    assert result["status"] == "posted"
    assert any("title" in r.message.lower() or "truncate" in r.message.lower() for r in caplog.records)


def test_title_at_limit_no_warning(caplog):
    gbp, drive = _make_clients()
    ok_title = "あ" * _GBP_OFFER_TITLE_LIMIT
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"), \
         caplog.at_level("WARNING"):
        run_offer(_STORE, ok_title, _TEXT, gbp, drive)
    title_warnings = [r for r in caplog.records if "title" in r.message.lower() and r.levelname == "WARNING"]
    assert not title_warnings


def test_long_text_logs_warning(caplog):
    gbp, drive = _make_clients()
    long_text = "あ" * (_GBP_POST_TEXT_LIMIT + 1)
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"), \
         caplog.at_level("WARNING"):
        result = run_offer(_STORE, _TITLE, long_text, gbp, drive)
    assert result["status"] == "posted"
    assert any("chars" in r.message.lower() or "limit" in r.message.lower() for r in caplog.records)


def test_text_at_limit_no_warning(caplog):
    gbp, drive = _make_clients()
    ok_text = "あ" * _GBP_POST_TEXT_LIMIT
    with patch("meo.tools.offer.record_post"), \
         patch("meo.tools.offer.record_post_content"), \
         caplog.at_level("WARNING"):
        run_offer(_STORE, _TITLE, ok_text, gbp, drive)
    text_warnings = [
        r for r in caplog.records
        if ("chars" in r.message.lower() or "limit" in r.message.lower()) and r.levelname == "WARNING"
    ]
    assert not text_warnings


# ---------------------------------------------------------------------------
# create_offer_post — BusinessProfileClient
# ---------------------------------------------------------------------------

def test_business_profile_create_offer_post_minimal():
    """create_offer_post with only required args sends correct API body."""
    from unittest.mock import MagicMock, patch as p
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"name": "accounts/1/locations/2/localPosts/1"}

    with p("meo.business_profile._AuthSession.post", return_value=mock_resp) as mock_post:
        client = BusinessProfileClient(creds)
        client._session._creds = creds
        with p.object(client._session, "post", return_value=mock_resp) as mp:
            client.create_offer_post(
                "accounts/1/locations/2",
                "タイトル",
                "本文テキスト",
            )
            body = mp.call_args.kwargs.get("json") or mp.call_args[1].get("json")

    assert body["topicType"] == "OFFER"
    assert body["languageCode"] == "ja"
    assert body["summary"] == "本文テキスト"
    assert body["event"]["title"] == "タイトル"
    assert "offer" not in body


def test_business_profile_create_offer_post_full():
    """create_offer_post with all optional fields sends them all."""
    from unittest.mock import MagicMock, patch as p
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"name": "accounts/1/locations/2/localPosts/2"}

    start = {"year": 2024, "month": 8, "day": 1}
    end = {"year": 2024, "month": 8, "day": 31}

    with p.object(
        BusinessProfileClient(creds)._session.__class__, "post", return_value=mock_resp
    ):
        client = BusinessProfileClient(creds)
        client._session._creds = creds
        with p.object(client._session, "post", return_value=mock_resp) as mp:
            client.create_offer_post(
                "accounts/1/locations/2",
                "タイトル",
                "本文",
                start_date=start, end_date=end,
                coupon_code="CODE10",
                redeem_url="https://example.com",
                terms="条件あり",
                media_url="https://lh3.example.com/img",
                call_to_action={"actionType": "BOOK", "url": "https://example.com/book"},
            )
            body = mp.call_args.kwargs.get("json") or mp.call_args[1].get("json")

    assert body["topicType"] == "OFFER"
    assert body["event"]["schedule"]["startDate"] == start
    assert body["event"]["schedule"]["endDate"] == end
    assert body["offer"]["couponCode"] == "CODE10"
    assert body["offer"]["redeemOnlineUrl"] == "https://example.com"
    assert body["offer"]["termsConditions"] == "条件あり"
    assert body["media"] == [{"mediaFormat": "PHOTO", "sourceUrl": "https://lh3.example.com/img"}]
    assert body["callToAction"] == {"actionType": "BOOK", "url": "https://example.com/book"}


def test_business_profile_create_offer_post_no_schedule_no_event_schedule():
    """create_offer_post with no dates still sets event.title but omits event.schedule."""
    from unittest.mock import MagicMock, patch as p
    from meo.business_profile import BusinessProfileClient
    from google.oauth2.credentials import Credentials

    creds = MagicMock(spec=Credentials)
    creds.valid = True
    creds.token = "fake-token"

    mock_resp = MagicMock()
    mock_resp.ok = True
    mock_resp.json.return_value = {"name": "accounts/1/locations/2/localPosts/3"}

    client = BusinessProfileClient(creds)
    client._session._creds = creds
    with p.object(client._session, "post", return_value=mock_resp) as mp:
        client.create_offer_post("accounts/1/locations/2", "オファータイトル", "本文")
        body = mp.call_args.kwargs.get("json") or mp.call_args[1].get("json")

    assert body["event"]["title"] == "オファータイトル"
    assert "schedule" not in body["event"]
