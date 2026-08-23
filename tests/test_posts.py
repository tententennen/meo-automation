"""Tests for local post creation — fully mocked, no Google credentials needed."""

from datetime import time
from unittest.mock import MagicMock, patch
import pytest

from meo.posts import run_post_for_store


@pytest.fixture(autouse=True)
def patch_record_post_content(monkeypatch):
    """Silence record_post_content for all tests — archiving is tested in test_state.py."""
    monkeypatch.setattr("meo.posts.record_post_content", lambda *a, **kw: None)


_STORE = {
    "key": "mybear_studio_kyoto",
    "name": "MYBEAR STUDIO 京都店",
    "industry": "fitness_studio",
    "location_id": "accounts/1/locations/3",
    "drive_folder_id": "folder_abc",
}

_IMAGE_META = {
    "id": "img1",
    "name": "gym.jpg",
    "mimeType": "image/jpeg",
    "webContentLink": "https://drive.google.com/uc?id=img1",
}

_FAKE_BYTES = b"\xff\xd8\xff"  # minimal fake JPEG header
_GBP_HOSTED_URL = "https://lh3.googleusercontent.com/hosted/img1"


def _make_mocks(post_text="今日も元気に！"):
    gbp = MagicMock()
    gbp.create_local_post.return_value = {"name": "accounts/1/locations/3/localPosts/99"}
    gbp.upload_media_bytes.return_value = _GBP_HOSTED_URL
    drive = MagicMock()
    drive.pick_random_image.return_value = _IMAGE_META
    drive.download_image.return_value = _FAKE_BYTES
    return gbp, drive, post_text


def test_dry_run_does_not_call_gbp():
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=True)
    gbp.create_local_post.assert_not_called()
    gbp.upload_media_bytes.assert_not_called()
    drive.download_image.assert_not_called()
    assert result["status"] == "dry_run"


def test_live_run_downloads_and_uploads_image():
    """Live run should download from Drive, upload to GBP, then create the post."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image") as mock_record_image, \
         patch("meo.posts.record_theme"):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=False)

    drive.download_image.assert_called_once_with("img1")
    gbp.upload_media_bytes.assert_called_once_with(
        _STORE["location_id"], _FAKE_BYTES, "image/jpeg"
    )
    # create_local_post should use the GBP-hosted URL; no CTA configured for this store
    gbp.create_local_post.assert_called_once_with(
        _STORE["location_id"], post_text, _GBP_HOSTED_URL, call_to_action=None
    )
    mock_record_image.assert_called_once_with(_STORE["key"], "img1")
    assert result["status"] == "posted"


def test_upload_failure_falls_back_to_web_content_link():
    """If GBP upload fails, fall back to the Drive webContentLink."""
    gbp, drive, post_text = _make_mocks()
    gbp.upload_media_bytes.side_effect = Exception("GBP API unavailable")
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=False)

    # Should still post using the webContentLink fallback
    gbp.create_local_post.assert_called_once()
    call_media_url = gbp.create_local_post.call_args.args[2]
    assert call_media_url == _IMAGE_META["webContentLink"]
    assert result["status"] == "posted"


def test_upload_failure_no_fallback_posts_without_photo():
    """If both GBP upload and webContentLink are unavailable, post without photo."""
    gbp, drive, post_text = _make_mocks()
    gbp.upload_media_bytes.side_effect = Exception("GBP API unavailable")
    # Remove webContentLink so there is no fallback
    drive.pick_random_image.return_value = {
        "id": "img1",
        "name": "gym.jpg",
        "mimeType": "image/jpeg",
        # no webContentLink
    }
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=False)

    gbp.create_local_post.assert_called_once()
    call_media_url = gbp.create_local_post.call_args.args[2]
    assert call_media_url is None
    assert result["status"] == "posted"


def test_drive_pick_image_error_falls_back_to_no_photo():
    """If pick_random_image raises (e.g. TODO/invalid folder ID), the post still succeeds."""
    gbp, drive, post_text = _make_mocks()
    drive.pick_random_image.side_effect = Exception("Drive API error: invalid folder")
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image") as mock_record_image, \
         patch("meo.posts.record_theme"):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=False)

    drive.download_image.assert_not_called()
    gbp.upload_media_bytes.assert_not_called()
    gbp.create_local_post.assert_called_once()
    call_media_url = gbp.create_local_post.call_args.args[2]
    assert call_media_url is None  # post with no photo
    mock_record_image.assert_not_called()  # no image to record
    assert result["status"] == "posted"


def test_no_image_posts_without_photo():
    gbp, drive, post_text = _make_mocks()
    drive.pick_random_image.return_value = None
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image") as mock_record_image, \
         patch("meo.posts.record_theme"):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=False)

    drive.download_image.assert_not_called()
    gbp.upload_media_bytes.assert_not_called()
    gbp.create_local_post.assert_called_once()
    call_media_url = gbp.create_local_post.call_args.args[2]
    assert call_media_url is None
    # No image was selected, so image history should not be updated
    mock_record_image.assert_not_called()
    assert result["status"] == "posted"


def test_todo_drive_folder_id_skips_drive_api_call():
    """When drive_folder_id is still the TODO placeholder, the Drive API must not be called.

    A TODO folder ID would produce a misleading Drive API error in the logs; the real
    cause is unconfigured config, not a Drive API problem.  The post should still go out
    (without a photo), and the Drive client must never be touched.
    """
    gbp, _, post_text = _make_mocks()
    drive = MagicMock()
    store_with_todo = {**_STORE, "drive_folder_id": "TODO: Google Drive folder ID"}
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image") as mock_record_image, \
         patch("meo.posts.record_theme"):
        result = run_post_for_store(store_with_todo, gbp, drive, dry_run=False)

    drive.pick_random_image.assert_not_called()
    drive.download_image.assert_not_called()
    gbp.create_local_post.assert_called_once()
    call_media_url = gbp.create_local_post.call_args.args[2]
    assert call_media_url is None
    mock_record_image.assert_not_called()
    assert result["status"] == "posted"


def test_already_posted_today_skips_without_api_call():
    """If should_post_today returns False, the post flow is skipped entirely."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.should_post_today", return_value=False), \
         patch("meo.posts.generate_post", return_value=post_text) as mock_gen:
        result = run_post_for_store(_STORE, gbp, drive, dry_run=False)

    mock_gen.assert_not_called()
    gbp.create_local_post.assert_not_called()
    assert result["status"] == "skipped"


def test_dry_run_bypasses_cadence_check():
    """Dry run always generates and logs the post, regardless of state."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.should_post_today", return_value=False), \
         patch("meo.posts.generate_post", return_value=post_text):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=True)

    # In dry-run mode the cadence guard is bypassed
    assert result["status"] == "dry_run"


# ---------------------------------------------------------------------------
# Theme rotation tests
# ---------------------------------------------------------------------------

def test_live_run_passes_forced_theme_to_generate_post():
    """generate_post() must always receive a forced_theme kwarg on the live path."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text) as mock_gen, \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"):
        run_post_for_store(_STORE, gbp, drive, dry_run=False)

    call_kwargs = mock_gen.call_args.kwargs
    # A theme must have been picked and forwarded
    assert "forced_theme" in call_kwargs
    assert isinstance(call_kwargs["forced_theme"], str)
    assert len(call_kwargs["forced_theme"]) > 0


def test_live_run_records_theme_after_successful_post():
    """record_theme() must be called with the store key and chosen theme."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme") as mock_record_theme:
        run_post_for_store(_STORE, gbp, drive, dry_run=False)

    mock_record_theme.assert_called_once()
    args = mock_record_theme.call_args.args
    assert args[0] == _STORE["key"]
    assert isinstance(args[1], str)


def test_dry_run_does_not_record_theme():
    """Dry run must not write any theme to state."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_theme") as mock_record_theme:
        result = run_post_for_store(_STORE, gbp, drive, dry_run=True)

    mock_record_theme.assert_not_called()
    assert result["status"] == "dry_run"


# ---------------------------------------------------------------------------
# Call-to-action tests
# ---------------------------------------------------------------------------

def test_call_to_action_passed_when_configured():
    """CTA from store config is forwarded to create_local_post as a keyword arg."""
    store_with_cta = {
        **_STORE,
        "call_to_action": {"action_type": "BOOK", "url": "https://example.com/book"},
    }
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"):
        run_post_for_store(store_with_cta, gbp, drive, dry_run=False)

    call_kwargs = gbp.create_local_post.call_args.kwargs
    assert call_kwargs.get("call_to_action") == {
        "actionType": "BOOK",
        "url": "https://example.com/book",
    }


def test_call_to_action_omitted_when_not_configured():
    """When store has no call_to_action config, None is passed to create_local_post."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"):
        run_post_for_store(_STORE, gbp, drive, dry_run=False)

    call_kwargs = gbp.create_local_post.call_args.kwargs
    assert call_kwargs.get("call_to_action") is None


def test_call_to_action_omitted_when_url_is_empty():
    """CTA with an empty URL string is treated as not configured."""
    store_empty_url = {
        **_STORE,
        "call_to_action": {"action_type": "BOOK", "url": ""},
    }
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"):
        run_post_for_store(store_empty_url, gbp, drive, dry_run=False)

    call_kwargs = gbp.create_local_post.call_args.kwargs
    assert call_kwargs.get("call_to_action") is None


# ---------------------------------------------------------------------------
# Content archiving test
# ---------------------------------------------------------------------------

def test_record_post_content_called_with_correct_args():
    """record_post_content must be called after a live post with store key and text."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"), \
         patch("meo.posts.record_post_content") as mock_archive:
        run_post_for_store(_STORE, gbp, drive, dry_run=False)

    mock_archive.assert_called_once()
    args = mock_archive.call_args.args
    assert args[0] == _STORE["key"]
    assert args[1] == post_text


def test_record_post_content_not_called_on_dry_run():
    """Dry run must not archive any content to state."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post_content") as mock_archive:
        run_post_for_store(_STORE, gbp, drive, dry_run=True)

    mock_archive.assert_not_called()


# ---------------------------------------------------------------------------
# --force flag test
# ---------------------------------------------------------------------------

def test_force_flag_bypasses_cadence_guard():
    """force=True posts even when should_post_today returns False."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=False) as mock_should, \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=False, force=True)

    gbp.create_local_post.assert_called_once()
    assert result["status"] == "posted"


# ---------------------------------------------------------------------------
# Per-store override tests
# ---------------------------------------------------------------------------

def test_per_store_cadence_override_passed_to_should_post_today():
    """A store with overrides.post_cadence_days uses its own cadence, not the global default."""
    store_with_override = {**_STORE, "overrides": {"post_cadence_days": 3}}
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.should_post_today", return_value=False) as mock_should:
        run_post_for_store(store_with_override, gbp, drive, dry_run=False)

    # should_post_today must be called with cadence_days=3 (not the global default of 1)
    mock_should.assert_called_once_with(store_with_override["key"], 3)


def test_pick_theme_returns_none_when_themes_list_is_empty():
    """_pick_theme returns None when the store's configured theme list is empty."""
    from meo.posts import _pick_theme
    with patch("meo.posts.get_recent_themes", return_value=[]):
        result = _pick_theme("the_body_kyoto", [])
    assert result is None


def test_todo_drive_folder_id_does_not_warn_no_images(caplog):
    """When drive_folder_id is a TODO placeholder, the 'No images found' WARNING must
    NOT be emitted.  The only log entry for the Drive path should be the DEBUG message
    'Drive folder not configured'; escalating to WARNING is misleading because the folder
    simply hasn't been configured yet — there is no Drive error or empty-folder condition.
    """
    import logging
    gbp, _, post_text = _make_mocks()
    drive = MagicMock()
    store_with_todo = {**_STORE, "drive_folder_id": "TODO: Google Drive folder ID"}
    with caplog.at_level(logging.DEBUG, logger="meo.posts"), \
         patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"):
        run_post_for_store(store_with_todo, gbp, drive, dry_run=False)

    warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert not any("No images found" in m for m in warning_msgs), (
        f"Expected no 'No images found' WARNING for unconfigured folder, got: {warning_msgs}"
    )


def test_drive_error_does_not_emit_no_images_warning(caplog):
    """When pick_random_image raises, only 'Drive image selection failed' is logged at
    WARNING; 'No images found in Drive folder' must NOT appear — that would be a duplicate
    and misleading (the folder may well have images; it's the API call that failed).
    """
    import logging
    gbp, drive, post_text = _make_mocks()
    drive.pick_random_image.side_effect = Exception("503 Service Unavailable")
    with caplog.at_level(logging.WARNING, logger="meo.posts"), \
         patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"):
        run_post_for_store(_STORE, gbp, drive, dry_run=False)

    warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("Drive image selection failed" in m for m in warning_msgs), (
        "Expected 'Drive image selection failed' warning"
    )
    assert not any("No images found" in m for m in warning_msgs), (
        f"Expected no 'No images found' duplicate WARNING after Drive error, got: {warning_msgs}"
    )


# ---------------------------------------------------------------------------
# _parse_time_window
# ---------------------------------------------------------------------------

def test_parse_time_window_valid_returns_start_and_end_times():
    from meo.posts import _parse_time_window
    start, end = _parse_time_window("06:00-23:00")
    assert start == time(6, 0)
    assert end == time(23, 0)


def test_parse_time_window_midnight_crossing_values():
    from meo.posts import _parse_time_window
    start, end = _parse_time_window("22:30-06:15")
    assert start == time(22, 30)
    assert end == time(6, 15)


def test_parse_time_window_bad_format_raises_value_error():
    from meo.posts import _parse_time_window
    with pytest.raises(ValueError, match="HH:MM-HH:MM"):
        _parse_time_window("6:0-23:0")  # missing leading zeros


def test_parse_time_window_missing_dash_raises_value_error():
    from meo.posts import _parse_time_window
    with pytest.raises(ValueError, match="HH:MM-HH:MM"):
        _parse_time_window("06:0023:00")


def test_parse_time_window_out_of_range_hour_raises_value_error():
    from meo.posts import _parse_time_window
    with pytest.raises(ValueError):
        _parse_time_window("25:00-23:00")


# ---------------------------------------------------------------------------
# _within_post_window
# ---------------------------------------------------------------------------

def test_within_post_window_none_always_returns_true():
    from meo.posts import _within_post_window
    assert _within_post_window(None) is True


def test_within_post_window_empty_string_always_returns_true():
    from meo.posts import _within_post_window
    assert _within_post_window("") is True


def test_within_post_window_inside_normal_range_returns_true():
    from meo.posts import _within_post_window
    assert _within_post_window("06:00-23:00", now=time(10, 0)) is True


def test_within_post_window_outside_normal_range_returns_false():
    from meo.posts import _within_post_window
    assert _within_post_window("06:00-23:00", now=time(2, 0)) is False


def test_within_post_window_at_exact_start_returns_true():
    from meo.posts import _within_post_window
    assert _within_post_window("06:00-23:00", now=time(6, 0)) is True


def test_within_post_window_at_exact_end_returns_true():
    from meo.posts import _within_post_window
    assert _within_post_window("06:00-23:00", now=time(23, 0)) is True


def test_within_post_window_midnight_crossing_inside_returns_true():
    from meo.posts import _within_post_window
    # "22:00-06:00": active from 22:00 through midnight to 06:00
    assert _within_post_window("22:00-06:00", now=time(23, 30)) is True


def test_within_post_window_midnight_crossing_early_morning_inside_returns_true():
    from meo.posts import _within_post_window
    assert _within_post_window("22:00-06:00", now=time(3, 0)) is True


def test_within_post_window_midnight_crossing_outside_returns_false():
    from meo.posts import _within_post_window
    assert _within_post_window("22:00-06:00", now=time(12, 0)) is False


def test_within_post_window_invalid_format_returns_true_with_warning(caplog):
    """A malformed window string (that should have been caught at startup) must
    not silently block posts — log a warning and return True.
    """
    import logging
    from meo.posts import _within_post_window
    with caplog.at_level(logging.WARNING, logger="meo.posts"):
        result = _within_post_window("not-valid", now=time(10, 0))
    assert result is True
    assert any("Invalid post_time_window_jst" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# run_post_for_store — time-window guard integration
# ---------------------------------------------------------------------------

def test_run_post_skips_when_outside_time_window():
    """When the current time is outside post_time_window_jst, the post is skipped
    and generate_post is never called (avoids an LLM API call).
    """
    gbp, drive, _ = _make_mocks()
    store_with_window = {**_STORE, "overrides": {"post_time_window_jst": "06:00-23:00"}}
    with patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.cfg.effective_defaults", return_value={
             "post_cadence_days": 1,
             "post_time_window_jst": "06:00-23:00",
         }), \
         patch("meo.posts._within_post_window", return_value=False) as mock_window, \
         patch("meo.posts.generate_post") as mock_gen:
        result = run_post_for_store(store_with_window, gbp, drive)

    assert result["status"] == "skipped_window"
    mock_gen.assert_not_called()
    gbp.create_local_post.assert_not_called()


def test_run_post_force_bypasses_time_window():
    """force=True must bypass the time-window guard so posts can go out at any hour."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"), \
         patch("meo.posts.cfg.effective_defaults", return_value={
             "post_cadence_days": 1,
             "post_time_window_jst": "06:00-23:00",
         }), \
         patch("meo.posts._within_post_window", return_value=False):
        result = run_post_for_store(_STORE, gbp, drive, force=True)

    # The window returned False, but force=True bypasses it — post should go through.
    assert result["status"] == "posted"
    gbp.create_local_post.assert_called_once()


def test_run_post_dry_run_skips_when_outside_time_window():
    """dry_run also respects the time window (faithfully simulates a live run)."""
    gbp, drive, _ = _make_mocks()
    with patch("meo.posts.cfg.effective_defaults", return_value={
             "post_cadence_days": 1,
             "post_time_window_jst": "06:00-23:00",
         }), \
         patch("meo.posts._within_post_window", return_value=False), \
         patch("meo.posts.generate_post") as mock_gen:
        result = run_post_for_store(_STORE, gbp, drive, dry_run=True)

    assert result["status"] == "skipped_window"
    mock_gen.assert_not_called()


# ---------------------------------------------------------------------------
# max_drive_image_bytes — posts.py passes size limit to pick_random_image
# ---------------------------------------------------------------------------

def test_max_drive_image_bytes_passed_to_pick_random_image():
    """posts.py reads max_drive_image_bytes from config and passes it to pick_random_image."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"), \
         patch("meo.posts.cfg.effective_defaults", return_value={
             "post_cadence_days": 1,
             "max_drive_image_bytes": 1_000_000,
         }):
        run_post_for_store(_STORE, gbp, drive, dry_run=False)

    drive.pick_random_image.assert_called_once()
    _, kwargs = drive.pick_random_image.call_args
    assert kwargs.get("max_bytes") == 1_000_000


def test_max_drive_image_bytes_defaults_to_5mb_when_absent():
    """When max_drive_image_bytes is absent from config, the default 5 MB is passed."""
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"), \
         patch("meo.posts.cfg.effective_defaults", return_value={
             "post_cadence_days": 1,
         }):
        run_post_for_store(_STORE, gbp, drive, dry_run=False)

    drive.pick_random_image.assert_called_once()
    _, kwargs = drive.pick_random_image.call_args
    assert kwargs.get("max_bytes") == 5_242_880


def test_all_oversized_images_does_not_emit_misleading_no_images_warning(caplog):
    """When pick_random_image returns None (e.g. all oversized), the generic
    'No images found in Drive folder' warning must NOT appear in posts.py logs.
    pick_random_image already logged the oversized reason; a second misleading
    message would confuse the operator into thinking the folder is empty.
    """
    import logging
    gbp, drive, post_text = _make_mocks()
    drive.pick_random_image.return_value = None  # simulates all-oversized or empty folder
    with caplog.at_level(logging.WARNING, logger="meo.posts"), \
         patch("meo.posts.generate_post", return_value=post_text), \
         patch("meo.posts.should_post_today", return_value=True), \
         patch("meo.posts.get_recent_images", return_value=[]), \
         patch("meo.posts.get_recent_themes", return_value=[]), \
         patch("meo.posts.record_post"), \
         patch("meo.posts.record_image"), \
         patch("meo.posts.record_theme"):
        run_post_for_store(_STORE, gbp, drive, dry_run=False)

    warning_msgs = [r.message for r in caplog.records if r.levelno >= logging.WARNING]
    assert not any("No images found" in m for m in warning_msgs), (
        f"Expected no 'No images found' WARNING when pick_random_image returns None, "
        f"got: {warning_msgs}"
    )
