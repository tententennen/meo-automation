"""Tests for the CLI entrypoint (main.py) — arg parsing, --store flag, exit codes."""

import pytest
from unittest.mock import patch, MagicMock

from meo.main import main


def _fake_store(key: str, location_id: str = "accounts/1/locations/1") -> dict:
    return {
        "key": key,
        "name": f"Store {key}",
        "industry": "beauty_salon",
        "location_id": location_id,
        "drive_folder_id": "folder_123",
    }


def _base_mocks():
    mock_creds = MagicMock()
    mock_gbp = MagicMock()
    mock_gbp.list_reviews.return_value = []
    mock_gbp.upload_media_bytes.return_value = "https://lh3.example.com/img"
    mock_drive = MagicMock()
    mock_drive.pick_random_image.return_value = None
    return mock_creds, mock_gbp, mock_drive


_ALL_STORES = [
    _fake_store("the_body_osaka_shinsaibashi", "accounts/1/locations/1"),
    _fake_store("the_body_kyoto", "accounts/1/locations/2"),
    _fake_store("mybear_studio_kyoto", "accounts/1/locations/3"),
]


def test_dry_run_all_stores_exits_0():
    """Dry run over all stores with mocked data should exit 0."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()
    with patch("sys.argv", ["meo", "--dry-run"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=_ALL_STORES), \
         patch("meo.content._call_llm", return_value="テストポスト"):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0


def test_store_filter_limits_processing():
    """--store <key> should cause only that store to be processed."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()
    processed_keys: list[str] = []

    def track_post(store, gbp, drive, *, dry_run=False):
        processed_keys.append(store["key"])
        return {"store_key": store["key"], "status": "dry_run", "post_text": ""}

    def track_reviews(store, gbp, *, dry_run=False):
        return {"store_key": store["key"], "replied": 0, "skipped": 0, "errors": []}

    with patch("sys.argv", ["meo", "--store", "the_body_kyoto", "--dry-run"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=_ALL_STORES), \
         patch("meo.main.run_post_for_store", side_effect=track_post), \
         patch("meo.main.run_reviews_for_store", side_effect=track_reviews):
        with pytest.raises(SystemExit):
            main()

    assert processed_keys == ["the_body_kyoto"]


def test_store_filter_multiple_keys():
    """--store can accept multiple keys."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()
    processed_keys: list[str] = []

    def track_post(store, gbp, drive, *, dry_run=False):
        processed_keys.append(store["key"])
        return {"store_key": store["key"], "status": "dry_run", "post_text": ""}

    def track_reviews(store, gbp, *, dry_run=False):
        return {"store_key": store["key"], "replied": 0, "skipped": 0, "errors": []}

    with patch("sys.argv", ["meo", "--store", "the_body_kyoto", "mybear_studio_kyoto", "--dry-run"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=_ALL_STORES), \
         patch("meo.main.run_post_for_store", side_effect=track_post), \
         patch("meo.main.run_reviews_for_store", side_effect=track_reviews):
        with pytest.raises(SystemExit) as exc:
            main()

    assert set(processed_keys) == {"the_body_kyoto", "mybear_studio_kyoto"}
    assert exc.value.code == 0


def test_unknown_store_key_exits_1():
    """--store with an unrecognized key should log an error and exit 1."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()
    with patch("sys.argv", ["meo", "--store", "does_not_exist"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=_ALL_STORES):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


def test_missing_credentials_exits_1():
    """Auth failure should exit 1 cleanly without a traceback."""
    with patch("sys.argv", ["meo"]), \
         patch("meo.main.get_credentials", side_effect=EnvironmentError("GOOGLE_CLIENT_ID not set")):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


def test_skip_posts_flag_skips_post_creation():
    """--skip-posts should not call run_post_for_store."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()

    def track_reviews(store, gbp, *, dry_run=False):
        return {"store_key": store["key"], "replied": 0, "skipped": 0, "errors": []}

    with patch("sys.argv", ["meo", "--skip-posts", "--dry-run"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=_ALL_STORES), \
         patch("meo.main.run_post_for_store") as mock_post, \
         patch("meo.main.run_reviews_for_store", side_effect=track_reviews):
        with pytest.raises(SystemExit):
            main()

    mock_post.assert_not_called()


def test_skip_reviews_flag_skips_review_replies():
    """--skip-reviews should not call run_reviews_for_store."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()

    def track_post(store, gbp, drive, *, dry_run=False):
        return {"store_key": store["key"], "status": "dry_run", "post_text": ""}

    with patch("sys.argv", ["meo", "--skip-reviews", "--dry-run"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=_ALL_STORES), \
         patch("meo.main.run_post_for_store", side_effect=track_post), \
         patch("meo.main.run_reviews_for_store") as mock_reviews:
        with pytest.raises(SystemExit):
            main()

    mock_reviews.assert_not_called()
