"""Tests for meo.tools.photo_audit — Drive photo inventory audit."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest

from meo.tools.photo_audit import (
    _LOW_PHOTO_WARNING_THRESHOLD,
    _format_output,
    run_photo_audit,
    main,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STORES = [
    {
        "key": "the_body_osaka_shinsaibashi",
        "name": "THE BODY 大阪 心斎橋店",
        "drive_folder_id": "folder_osaka_abc123",
    },
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "drive_folder_id": "folder_kyoto_xyz789",
    },
    {
        "key": "mybear_studio_kyoto",
        "name": "MYBEAR STUDIO 京都店",
        "drive_folder_id": "TODO: Google Drive folder ID",
    },
]

_FOLDER_OSAKA = [
    {"id": "img_a1", "name": "spring_campaign.jpg", "mimeType": "image/jpeg"},
    {"id": "img_a2", "name": "summer_menu.jpg",     "mimeType": "image/jpeg"},
    {"id": "img_a3", "name": "staff_tanaka.jpg",    "mimeType": "image/jpeg"},
    {"id": "img_a4", "name": "interior_01.jpg",     "mimeType": "image/jpeg"},
    {"id": "img_a5", "name": "treatment_room.jpg",  "mimeType": "image/jpeg"},
    {"id": "img_a6", "name": "product_lineup.jpg",  "mimeType": "image/jpeg"},
    {"id": "img_a7", "name": "reception_area.jpg",  "mimeType": "image/jpeg"},
    {"id": "img_a8", "name": "autumn_promo.jpg",    "mimeType": "image/jpeg"},
]

_FOLDER_KYOTO = [
    {"id": "img_b1", "name": "exterior.jpg",        "mimeType": "image/jpeg"},
    {"id": "img_b2", "name": "lobby.jpg",            "mimeType": "image/jpeg"},
]


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.photo_audit.cfg.store_list", lambda: list(_STORES))


@pytest.fixture(autouse=True)
def _patch_recent_images(monkeypatch):
    """By default no recent images in state.json."""
    monkeypatch.setattr("meo.tools.photo_audit.get_recent_images", lambda key: [])


# ---------------------------------------------------------------------------
# run_photo_audit — offline mode
# ---------------------------------------------------------------------------

def test_run_photo_audit_offline_returns_one_result_per_store():
    results = run_photo_audit(_STORES)
    assert len(results) == 3


def test_run_photo_audit_offline_configured_store_has_no_warnings():
    results = run_photo_audit(_STORES[:2])
    for r in results:
        assert r["warnings"] == []


def test_run_photo_audit_offline_todo_store_has_warning():
    results = run_photo_audit([_STORES[2]])
    assert len(results[0]["warnings"]) == 1
    assert "TODO" in results[0]["warnings"][0]


def test_run_photo_audit_offline_folder_images_none():
    results = run_photo_audit(_STORES)
    for r in results:
        assert r["folder_images"] is None
        assert r["folder_image_count"] is None
        assert r["fresh_image_count"] is None


def test_run_photo_audit_offline_recent_images_from_state(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.photo_audit.get_recent_images",
        lambda key: ["img_a1", "img_a2"] if key == "the_body_osaka_shinsaibashi" else [],
    )
    results = run_photo_audit([_STORES[0]])
    assert results[0]["recent_image_ids"] == ["img_a1", "img_a2"]
    assert results[0]["recent_image_count"] == 2


def test_run_photo_audit_offline_empty_folder_id_not_configured():
    store = {
        "key": "test_store",
        "name": "Test Store",
        "drive_folder_id": "",
    }
    results = run_photo_audit([store])
    assert results[0]["folder_configured"] is False
    assert any("TODO" in w for w in results[0]["warnings"])


def test_run_photo_audit_offline_folder_configured_flag_true_for_real_id():
    results = run_photo_audit([_STORES[0]])
    assert results[0]["folder_configured"] is True


def test_run_photo_audit_offline_folder_configured_flag_false_for_todo():
    results = run_photo_audit([_STORES[2]])
    assert results[0]["folder_configured"] is False


# ---------------------------------------------------------------------------
# run_photo_audit — live mode
# ---------------------------------------------------------------------------

def _make_drive(folder_images_map: dict):
    """Return a mock DriveClient whose list_images returns the given map."""
    drive = MagicMock()
    drive.list_images.side_effect = lambda folder_id: folder_images_map.get(folder_id, [])
    return drive


def test_run_photo_audit_live_returns_folder_image_count():
    drive = _make_drive({"folder_osaka_abc123": _FOLDER_OSAKA})
    results = run_photo_audit([_STORES[0]], drive=drive)
    assert results[0]["folder_image_count"] == len(_FOLDER_OSAKA)


def test_run_photo_audit_live_all_images_fresh_when_no_recent():
    drive = _make_drive({"folder_osaka_abc123": _FOLDER_OSAKA})
    results = run_photo_audit([_STORES[0]], drive=drive)
    assert results[0]["fresh_image_count"] == len(_FOLDER_OSAKA)


def test_run_photo_audit_live_recent_images_subtracted_from_fresh(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.photo_audit.get_recent_images",
        lambda key: ["img_a1", "img_a2"] if key == "the_body_osaka_shinsaibashi" else [],
    )
    drive = _make_drive({"folder_osaka_abc123": _FOLDER_OSAKA})
    results = run_photo_audit([_STORES[0]], drive=drive)
    # 8 total - 2 recently used = 6 fresh
    assert results[0]["fresh_image_count"] == len(_FOLDER_OSAKA) - 2


def test_run_photo_audit_live_no_warning_when_fresh_count_at_threshold():
    """Exactly _LOW_PHOTO_WARNING_THRESHOLD fresh images → no warning."""
    images = [
        {"id": f"img_{i}", "name": f"photo_{i}.jpg"} for i in range(_LOW_PHOTO_WARNING_THRESHOLD)
    ]
    drive = _make_drive({"folder_osaka_abc123": images})
    results = run_photo_audit([_STORES[0]], drive=drive)
    assert results[0]["warnings"] == []


def test_run_photo_audit_live_warning_when_fresh_count_below_threshold():
    """Fewer than _LOW_PHOTO_WARNING_THRESHOLD fresh images → warning."""
    images = [
        {"id": f"img_{i}", "name": f"photo_{i}.jpg"} for i in range(_LOW_PHOTO_WARNING_THRESHOLD - 1)
    ]
    drive = _make_drive({"folder_osaka_abc123": images})
    results = run_photo_audit([_STORES[0]], drive=drive)
    assert any("fresh photo" in w for w in results[0]["warnings"])


def test_run_photo_audit_live_warning_for_empty_folder():
    drive = _make_drive({"folder_osaka_abc123": []})
    results = run_photo_audit([_STORES[0]], drive=drive)
    assert any("empty" in w for w in results[0]["warnings"])


def test_run_photo_audit_live_drive_api_error_adds_warning():
    drive = MagicMock()
    drive.list_images.side_effect = RuntimeError("403 Forbidden")
    results = run_photo_audit([_STORES[0]], drive=drive)
    assert any("Drive API error" in w for w in results[0]["warnings"])
    assert results[0]["folder_images"] is None


def test_run_photo_audit_live_skips_drive_for_unconfigured_store():
    drive = MagicMock()
    results = run_photo_audit([_STORES[2]], drive=drive)
    drive.list_images.assert_not_called()
    assert results[0]["folder_images"] is None


def test_run_photo_audit_live_folder_images_list_returned():
    drive = _make_drive({"folder_osaka_abc123": _FOLDER_OSAKA})
    results = run_photo_audit([_STORES[0]], drive=drive)
    assert results[0]["folder_images"] == _FOLDER_OSAKA


# ---------------------------------------------------------------------------
# _format_output — offline mode
# ---------------------------------------------------------------------------

def test_format_offline_shows_offline_mode_label():
    results = run_photo_audit([_STORES[0]])
    output = _format_output(results, live=False)
    assert "OFFLINE" in output


def test_format_offline_shows_store_name_and_key():
    results = run_photo_audit([_STORES[0]])
    output = _format_output(results, live=False)
    assert "THE BODY 大阪 心斎橋店" in output
    assert "the_body_osaka_shinsaibashi" in output


def test_format_offline_shows_configured_folder_id():
    results = run_photo_audit([_STORES[0]])
    output = _format_output(results, live=False)
    assert "folder_osaka_abc123" in output
    assert "✓" in output


def test_format_offline_shows_not_configured_for_todo_store():
    results = run_photo_audit([_STORES[2]])
    output = _format_output(results, live=False)
    assert "NOT CONFIGURED" in output
    assert "✗" in output


def test_format_offline_shows_recent_image_count(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.photo_audit.get_recent_images",
        lambda key: ["img_a1", "img_a2", "img_a3"] if key == "the_body_osaka_shinsaibashi" else [],
    )
    results = run_photo_audit([_STORES[0]])
    output = _format_output(results, live=False)
    assert "3 image ID(s)" in output


def test_format_offline_does_not_show_folder_total():
    results = run_photo_audit([_STORES[0]])
    output = _format_output(results, live=False)
    assert "Folder total" not in output


def test_format_offline_shows_warning():
    results = run_photo_audit([_STORES[2]])
    output = _format_output(results, live=False)
    assert "⚠" in output


# ---------------------------------------------------------------------------
# _format_output — live mode
# ---------------------------------------------------------------------------

def test_format_live_shows_live_mode_label():
    drive = _make_drive({"folder_osaka_abc123": _FOLDER_OSAKA})
    results = run_photo_audit([_STORES[0]], drive=drive)
    output = _format_output(results, live=True)
    assert "LIVE" in output


def test_format_live_shows_folder_total_and_fresh():
    drive = _make_drive({"folder_osaka_abc123": _FOLDER_OSAKA})
    results = run_photo_audit([_STORES[0]], drive=drive)
    output = _format_output(results, live=True)
    assert "Folder total" in output
    assert "Fresh" in output


def test_format_live_shows_photo_list_with_fresh_marker():
    drive = _make_drive({"folder_osaka_abc123": [
        {"id": "img_new", "name": "new_photo.jpg"},
    ]})
    results = run_photo_audit([_STORES[0]], drive=drive)
    output = _format_output(results, live=True)
    assert "✓ fresh" in output
    assert "new_photo.jpg" in output


def test_format_live_shows_used_marker_for_recent_images(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.photo_audit.get_recent_images",
        lambda key: ["img_a1"],
    )
    drive = _make_drive({"folder_osaka_abc123": [
        {"id": "img_a1", "name": "recently_used.jpg"},
    ]})
    results = run_photo_audit([_STORES[0]], drive=drive)
    output = _format_output(results, live=True)
    assert "⟳ used" in output
    assert "recently_used.jpg" in output


def test_format_live_shows_drive_query_failed_for_drive_error():
    drive = MagicMock()
    drive.list_images.side_effect = RuntimeError("network error")
    results = run_photo_audit([_STORES[0]], drive=drive)
    output = _format_output(results, live=True)
    assert "Drive query failed" in output


def test_format_live_does_not_show_photo_list_for_empty_folder():
    drive = _make_drive({"folder_osaka_abc123": []})
    results = run_photo_audit([_STORES[0]], drive=drive)
    output = _format_output(results, live=True)
    assert "Photos:" not in output


def test_format_live_photos_sorted_alphabetically():
    images = [
        {"id": "img_z", "name": "zebra.jpg"},
        {"id": "img_a", "name": "apple.jpg"},
        {"id": "img_m", "name": "mango.jpg"},
    ]
    drive = _make_drive({"folder_osaka_abc123": images})
    results = run_photo_audit([_STORES[0]], drive=drive)
    output = _format_output(results, live=True)
    apple_pos = output.index("apple.jpg")
    mango_pos = output.index("mango.jpg")
    zebra_pos = output.index("zebra.jpg")
    assert apple_pos < mango_pos < zebra_pos


def test_format_live_unconfigured_store_does_not_show_drive_query_failed():
    """Unconfigured store has no Drive call, so 'Drive query failed' must not appear."""
    results = run_photo_audit([_STORES[2]])
    output = _format_output(results, live=True)
    assert "Drive query failed" not in output


# ---------------------------------------------------------------------------
# main() — argument parsing and exit codes
# ---------------------------------------------------------------------------

def test_main_offline_default_exits_0_no_warnings(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meo-photo-audit"])
    monkeypatch.setattr("meo.tools.photo_audit.cfg.store_list", lambda: [_STORES[0]])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0


def test_main_offline_exits_1_when_store_has_warning(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meo-photo-audit"])
    monkeypatch.setattr("meo.tools.photo_audit.cfg.store_list", lambda: [_STORES[2]])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_store_filter_accepted(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meo-photo-audit", "--store", "the_body_kyoto"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "THE BODY 京都店" in out
    assert "THE BODY 大阪 心斎橋店" not in out


def test_main_unknown_store_key_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meo-photo-audit", "--store", "nonexistent_store"])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "nonexistent_store" in err


def test_main_live_flag_initialises_drive_client(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["meo-photo-audit", "--live"])
    monkeypatch.setattr("meo.tools.photo_audit.cfg.store_list", lambda: [_STORES[0]])
    mock_drive = MagicMock()
    mock_drive.list_images.return_value = _FOLDER_OSAKA

    with patch("meo.auth.get_credentials", return_value=MagicMock()):
        with patch("meo.drive.DriveClient", return_value=mock_drive):
            with pytest.raises(SystemExit) as exc:
                main()
    assert exc.value.code == 0
    mock_drive.list_images.assert_called_once_with("folder_osaka_abc123")


def test_main_live_drive_init_failure_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meo-photo-audit", "--live"])
    monkeypatch.setattr("meo.tools.photo_audit.cfg.store_list", lambda: [_STORES[0]])
    with patch("meo.auth.get_credentials", side_effect=RuntimeError("missing env")):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1
    err = capsys.readouterr().err
    assert "Drive client" in err


def test_main_live_drive_client_called_with_credentials(monkeypatch):
    """Verify DriveClient is instantiated with credentials from get_credentials."""
    monkeypatch.setattr(sys, "argv", ["meo-photo-audit", "--live"])
    monkeypatch.setattr("meo.tools.photo_audit.cfg.store_list", lambda: [_STORES[0]])
    mock_creds = MagicMock()
    mock_drive = MagicMock()
    mock_drive.list_images.return_value = _FOLDER_OSAKA

    with patch("meo.auth.get_credentials", return_value=mock_creds) as mock_get_creds:
        with patch("meo.drive.DriveClient", return_value=mock_drive) as mock_dc:
            with pytest.raises(SystemExit):
                main()

    mock_get_creds.assert_called_once()
    mock_dc.assert_called_once_with(mock_creds)


def test_main_output_printed_to_stdout(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meo-photo-audit"])
    monkeypatch.setattr("meo.tools.photo_audit.cfg.store_list", lambda: [_STORES[0]])
    with pytest.raises(SystemExit):
        main()
    out = capsys.readouterr().out
    assert "MEO Automation" in out
    assert "Photo Inventory Audit" in out


def test_main_no_store_arg_audits_all_stores(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["meo-photo-audit"])
    with pytest.raises(SystemExit):
        main()
    out = capsys.readouterr().out
    assert "THE BODY 大阪 心斎橋店" in out
    assert "THE BODY 京都店" in out
    assert "MYBEAR STUDIO 京都店" in out
