"""Tests for local post creation — fully mocked, no Google credentials needed."""

from unittest.mock import MagicMock, patch
import pytest

from meo.posts import run_post_for_store


_STORE = {
    "key": "mybear_studio_kyoto",
    "name": "MYBEAR STUDIO 京都店",
    "industry": "fitness_studio",
    "location_id": "accounts/1/locations/3",
    "drive_folder_id": "folder_abc",
}


def _make_mocks(post_text="今日も元気に！", image_name="gym.jpg"):
    gbp = MagicMock()
    gbp.create_local_post.return_value = {"name": "accounts/1/locations/3/localPosts/99"}
    drive = MagicMock()
    drive.pick_random_image.return_value = {
        "id": "img1",
        "name": image_name,
        "mimeType": "image/jpeg",
        "webContentLink": "https://drive.google.com/uc?id=img1",
    }
    return gbp, drive, post_text


def test_dry_run_does_not_call_gbp():
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=True)
    gbp.create_local_post.assert_not_called()
    assert result["status"] == "dry_run"


def test_live_run_calls_create_local_post():
    gbp, drive, post_text = _make_mocks()
    with patch("meo.posts.generate_post", return_value=post_text):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=False)
    gbp.create_local_post.assert_called_once()
    assert result["status"] == "posted"


def test_no_image_posts_without_photo():
    gbp, drive, post_text = _make_mocks()
    drive.pick_random_image.return_value = None
    with patch("meo.posts.generate_post", return_value=post_text):
        result = run_post_for_store(_STORE, gbp, drive, dry_run=False)
    # Should still post, just without media_url
    call_kwargs = gbp.create_local_post.call_args
    assert call_kwargs.args[2] is None or call_kwargs.kwargs.get("media_url") is None
    assert result["status"] == "posted"
