"""Tests for local post creation — fully mocked, no Google credentials needed."""

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
