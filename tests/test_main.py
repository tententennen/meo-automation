"""Tests for the CLI entrypoint (main.py) — arg parsing, --store flag, exit codes."""

import pytest
from unittest.mock import patch, MagicMock

from meo.main import main


@pytest.fixture(autouse=True)
def bypass_validation(monkeypatch):
    """Skip config validation for all main.py tests — it is tested separately in test_validator.py."""
    monkeypatch.setattr("meo.main.validate_all", lambda **_: [])


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

    def track_post(store, gbp, drive, *, dry_run=False, force=False):
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

    def track_post(store, gbp, drive, *, dry_run=False, force=False):
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

    def track_post(store, gbp, drive, *, dry_run=False, force=False):
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


def test_force_flag_forwarded_to_run_post_for_store():
    """--force must be forwarded as force=True to run_post_for_store."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()
    captured_kwargs: list[dict] = []

    def track_post(store, gbp, drive, *, dry_run=False, force=False):
        captured_kwargs.append({"dry_run": dry_run, "force": force})
        return {"store_key": store["key"], "status": "posted", "post_name": "p1"}

    def track_reviews(store, gbp, *, dry_run=False):
        return {"store_key": store["key"], "replied": 0, "skipped": 0, "deferred": 0, "errors": []}

    one_store = [_fake_store("the_body_kyoto", "accounts/1/locations/2")]
    with patch("sys.argv", ["meo", "--store", "the_body_kyoto", "--force"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=one_store), \
         patch("meo.main.run_post_for_store", side_effect=track_post), \
         patch("meo.main.run_reviews_for_store", side_effect=track_reviews):
        with pytest.raises(SystemExit):
            main()

    assert len(captured_kwargs) == 1
    assert captured_kwargs[0]["force"] is True
    assert captured_kwargs[0]["dry_run"] is False


# ---------------------------------------------------------------------------
# Error-path coverage — branches not exercised by the happy-path tests above
# ---------------------------------------------------------------------------

def test_config_validation_errors_exit_1_before_auth(monkeypatch):
    """validate_all() returning errors must exit 1 without ever calling get_credentials."""
    # Override the autouse bypass so this test actually sees an error.
    monkeypatch.setattr("meo.main.validate_all", lambda **_: ["store.location_id is required"])
    with patch("sys.argv", ["meo"]), \
         patch("meo.main.get_credentials") as mock_auth:
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    mock_auth.assert_not_called()


def test_store_with_todo_location_id_is_skipped_and_exits_1():
    """A store whose location_id value contains 'TODO' must be skipped; exit code must be 1."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()
    todo_store = _fake_store("the_body_kyoto", location_id="TODO_fill_in_location_id")

    with patch("sys.argv", ["meo", "--dry-run"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=[todo_store]), \
         patch("meo.main.run_post_for_store") as mock_post, \
         patch("meo.main.run_reviews_for_store") as mock_reviews:
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 1
    mock_post.assert_not_called()
    mock_reviews.assert_not_called()


def test_store_with_todo_drive_folder_id_logs_warning_but_exits_0():
    """A TODO drive_folder_id logs a warning but does NOT cause had_error; exit code is 0."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()
    store = {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
        "location_id": "accounts/1/locations/2",
        "drive_folder_id": "TODO_fill_in_drive_folder",
    }

    def track_post(s, gbp, drive, *, dry_run=False, force=False):
        return {"store_key": s["key"], "status": "dry_run", "post_text": "テスト"}

    def track_reviews(s, gbp, *, dry_run=False):
        return {"store_key": s["key"], "replied": 0, "skipped": 0, "errors": []}

    with patch("sys.argv", ["meo", "--dry-run"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=[store]), \
         patch("meo.main.run_post_for_store", side_effect=track_post), \
         patch("meo.main.run_reviews_for_store", side_effect=track_reviews):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 0  # warning only, not an error


def test_post_exception_is_caught_and_causes_exit_1():
    """An unhandled exception from run_post_for_store must be caught; exit code must be 1."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()
    one_store = [_fake_store("the_body_kyoto", "accounts/1/locations/2")]

    def track_reviews(s, gbp, *, dry_run=False):
        return {"store_key": s["key"], "replied": 0, "skipped": 0, "errors": []}

    with patch("sys.argv", ["meo", "--dry-run"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=one_store), \
         patch("meo.main.run_post_for_store", side_effect=RuntimeError("GBP timeout")), \
         patch("meo.main.run_reviews_for_store", side_effect=track_reviews):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 1


def test_reviews_exception_is_caught_and_causes_exit_1():
    """An unhandled exception from run_reviews_for_store must be caught; exit code must be 1."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()
    one_store = [_fake_store("the_body_kyoto", "accounts/1/locations/2")]

    def track_post(s, gbp, drive, *, dry_run=False, force=False):
        return {"store_key": s["key"], "status": "dry_run", "post_text": "テスト"}

    with patch("sys.argv", ["meo", "--dry-run"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=one_store), \
         patch("meo.main.run_post_for_store", side_effect=track_post), \
         patch("meo.main.run_reviews_for_store", side_effect=RuntimeError("Review API error")):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 1


def test_reviews_result_with_errors_key_causes_exit_1():
    """run_reviews_for_store returning a result dict that contains errors must cause exit 1."""
    mock_creds, mock_gbp, mock_drive = _base_mocks()
    one_store = [_fake_store("the_body_kyoto", "accounts/1/locations/2")]

    def track_post(s, gbp, drive, *, dry_run=False, force=False):
        return {"store_key": s["key"], "status": "dry_run", "post_text": "テスト"}

    def reviews_with_errors(s, gbp, *, dry_run=False):
        return {"store_key": s["key"], "replied": 0, "errors": ["GBP returned 500"]}

    with patch("sys.argv", ["meo", "--dry-run"]), \
         patch("meo.main.get_credentials", return_value=mock_creds), \
         patch("meo.main.BusinessProfileClient", return_value=mock_gbp), \
         patch("meo.main.DriveClient", return_value=mock_drive), \
         patch("meo.main.cfg.store_list", return_value=one_store), \
         patch("meo.main.run_post_for_store", side_effect=track_post), \
         patch("meo.main.run_reviews_for_store", side_effect=reviews_with_errors):
        with pytest.raises(SystemExit) as exc:
            main()

    assert exc.value.code == 1
