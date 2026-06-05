"""Tests for the meo-health smoke-test tool."""

from unittest.mock import MagicMock, patch

import pytest

from meo.tools.health import run_health, main


_STORE = {
    "key": "the_body_kyoto",
    "name": "THE BODY 京都店",
    "location_id": "accounts/1/locations/1",
    "drive_folder_id": "folder_abc",
    "industry": "beauty_salon",
}


@pytest.fixture(autouse=True)
def patch_store_list(monkeypatch):
    monkeypatch.setattr("meo.tools.health.cfg.store_list", lambda: [_STORE])


# ---------------------------------------------------------------------------
# run_health() unit tests
# ---------------------------------------------------------------------------

def test_health_all_ok():
    with patch("meo.tools.health.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.health.BusinessProfileClient") as mock_gbp, \
         patch("meo.tools.health.DriveClient") as mock_drive:
        mock_gbp.return_value.list_reviews.return_value = [{"name": "rev1"}]
        mock_drive.return_value.list_images.return_value = [{"id": "img1"}]
        results = run_health()
    assert len(results) == 1
    r = results[0]
    assert r["ok"] is True
    assert "OK (1 review(s))" in r["checks"]["gbp_list_reviews"]
    assert "OK (1 image(s))" in r["checks"]["drive_list_images"]


def test_health_gbp_api_error():
    with patch("meo.tools.health.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.health.BusinessProfileClient") as mock_gbp, \
         patch("meo.tools.health.DriveClient") as mock_drive:
        mock_gbp.return_value.list_reviews.side_effect = RuntimeError("403 Forbidden")
        mock_drive.return_value.list_images.return_value = []
        results = run_health()
    assert results[0]["ok"] is False
    assert results[0]["checks"]["gbp_list_reviews"].startswith("ERROR")


def test_health_drive_api_error():
    with patch("meo.tools.health.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.health.BusinessProfileClient") as mock_gbp, \
         patch("meo.tools.health.DriveClient") as mock_drive:
        mock_gbp.return_value.list_reviews.return_value = []
        mock_drive.return_value.list_images.side_effect = RuntimeError("404 folder not found")
        results = run_health()
    assert results[0]["ok"] is False
    assert results[0]["checks"]["drive_list_images"].startswith("ERROR")


def test_health_unconfigured_location_id(monkeypatch):
    todo_store = dict(_STORE, location_id="TODO: accounts/{account_id}/locations/{location_id}")
    monkeypatch.setattr("meo.tools.health.cfg.store_list", lambda: [todo_store])
    with patch("meo.tools.health.get_credentials", return_value=MagicMock()):
        results = run_health()
    assert results[0]["ok"] is False
    assert "location_id" in results[0]["checks"]


def test_health_unconfigured_drive_folder_id_is_warning_not_fatal(monkeypatch):
    """Missing drive_folder_id flags a warning but does not set ok=False."""
    todo_store = dict(_STORE, drive_folder_id="TODO: Google Drive folder ID")
    monkeypatch.setattr("meo.tools.health.cfg.store_list", lambda: [todo_store])
    with patch("meo.tools.health.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.health.BusinessProfileClient") as mock_gbp:
        mock_gbp.return_value.list_reviews.return_value = []
        results = run_health()
    assert results[0]["ok"] is True
    assert "drive_folder_id" in results[0]["checks"]


def test_health_auth_failure():
    with patch("meo.tools.health.get_credentials", side_effect=EnvironmentError("GOOGLE_REFRESH_TOKEN not set")):
        results = run_health()
    assert len(results) == 1
    assert "auth_error" in results[0]
    assert "GOOGLE_REFRESH_TOKEN" in results[0]["auth_error"]


def test_health_store_key_filter(monkeypatch):
    two_stores = [
        dict(_STORE, key="store_a", name="Store A", location_id="accounts/1/locations/1"),
        dict(_STORE, key="store_b", name="Store B", location_id="accounts/1/locations/2"),
    ]
    monkeypatch.setattr("meo.tools.health.cfg.store_list", lambda: two_stores)
    with patch("meo.tools.health.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.health.BusinessProfileClient") as mock_gbp, \
         patch("meo.tools.health.DriveClient") as mock_drive:
        mock_gbp.return_value.list_reviews.return_value = []
        mock_drive.return_value.list_images.return_value = []
        results = run_health(["store_a"])
    assert len(results) == 1
    assert results[0]["store_key"] == "store_a"


# ---------------------------------------------------------------------------
# main() CLI tests
# ---------------------------------------------------------------------------

def test_main_exits_0_when_all_ok(capsys):
    with patch("meo.tools.health.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.health.BusinessProfileClient") as mock_gbp, \
         patch("meo.tools.health.DriveClient") as mock_drive, \
         patch("sys.argv", ["meo-health"]):
        mock_gbp.return_value.list_reviews.return_value = []
        mock_drive.return_value.list_images.return_value = []
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "All checks passed" in out


def test_main_exits_1_when_api_error(capsys):
    with patch("meo.tools.health.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.health.BusinessProfileClient") as mock_gbp, \
         patch("meo.tools.health.DriveClient") as mock_drive, \
         patch("sys.argv", ["meo-health"]):
        mock_gbp.return_value.list_reviews.side_effect = RuntimeError("API down")
        mock_drive.return_value.list_images.return_value = []
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Some checks failed" in out


def test_main_exits_1_on_auth_failure(capsys):
    with patch("meo.tools.health.get_credentials", side_effect=EnvironmentError("no creds")), \
         patch("sys.argv", ["meo-health"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Authentication failed" in out


def test_main_exits_1_on_unknown_store_key(capsys):
    with patch("sys.argv", ["meo-health", "--store", "nonexistent_store"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Unknown store key" in out
