"""Tests for the meo-reset state reset CLI."""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import meo.state as state_mod
from meo.tools.reset import run_reset, main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STORES = [
    {"key": "the_body_kyoto", "name": "THE BODY 京都店"},
    {"key": "mybear_studio_kyoto", "name": "MYBEAR STUDIO 京都店"},
]


@pytest.fixture(autouse=True)
def patch_state_file(tmp_path, monkeypatch):
    """Redirect the state file to a temp directory for every test."""
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "_STATE_FILE", state_file)
    return state_file


@pytest.fixture(autouse=True)
def patch_store_list(monkeypatch):
    monkeypatch.setattr("meo.tools.reset.cfg.store_list", lambda: _STORES)


def _write_full_state(state_file: Path) -> None:
    """Populate state.json with data for both test stores."""
    data = {
        "last_post": {
            "the_body_kyoto": "2024-06-15",
            "mybear_studio_kyoto": "2024-06-15",
        },
        "recent_images": {
            "the_body_kyoto": ["img1"],
            "mybear_studio_kyoto": ["img2"],
        },
        "recent_themes": {
            "the_body_kyoto": ["テーマA"],
            "mybear_studio_kyoto": ["テーマB"],
        },
        "replied_reviews": {
            "the_body_kyoto": ["rev1"],
            "mybear_studio_kyoto": ["rev2"],
        },
    }
    state_file.write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# run_reset() unit tests
# ---------------------------------------------------------------------------

def test_run_reset_post_guard_all_stores(patch_state_file):
    _write_full_state(patch_state_file)
    result = run_reset("post-guard")
    assert set(result["post_guard"]) == {"the_body_kyoto", "mybear_studio_kyoto"}
    assert state_mod._load().get("last_post") == {}


def test_run_reset_post_guard_specific_store(patch_state_file):
    _write_full_state(patch_state_file)
    result = run_reset("post-guard", store_key="the_body_kyoto")
    assert result["post_guard"] == ["the_body_kyoto"]
    # Other store untouched
    remaining = state_mod._load()["last_post"]
    assert "the_body_kyoto" not in remaining
    assert remaining.get("mybear_studio_kyoto") == "2024-06-15"


def test_run_reset_image_history_all_stores(patch_state_file):
    _write_full_state(patch_state_file)
    result = run_reset("image-history")
    assert set(result["image_history"]) == {"the_body_kyoto", "mybear_studio_kyoto"}
    assert state_mod._load().get("recent_images") == {}


def test_run_reset_image_history_specific_store(patch_state_file):
    _write_full_state(patch_state_file)
    result = run_reset("image-history", store_key="the_body_kyoto")
    assert result["image_history"] == ["the_body_kyoto"]
    assert state_mod._load()["recent_images"].get("mybear_studio_kyoto") == ["img2"]


def test_run_reset_theme_history_all_stores(patch_state_file):
    _write_full_state(patch_state_file)
    result = run_reset("theme-history")
    assert set(result["theme_history"]) == {"the_body_kyoto", "mybear_studio_kyoto"}
    assert state_mod._load().get("recent_themes") == {}


def test_run_reset_replied_reviews_all_stores(patch_state_file):
    _write_full_state(patch_state_file)
    result = run_reset("replied-reviews")
    assert set(result["replied_reviews"]) == {"the_body_kyoto", "mybear_studio_kyoto"}
    assert state_mod._load().get("replied_reviews") == {}


def test_run_reset_all_clears_every_section(patch_state_file):
    _write_full_state(patch_state_file)
    result = run_reset("all")
    assert set(result.keys()) == {"post_guard", "image_history", "theme_history", "replied_reviews"}
    loaded = state_mod._load()
    assert loaded.get("last_post") == {}
    assert loaded.get("recent_images") == {}
    assert loaded.get("recent_themes") == {}
    assert loaded.get("replied_reviews") == {}


def test_run_reset_all_specific_store_leaves_other_intact(patch_state_file):
    _write_full_state(patch_state_file)
    run_reset("all", store_key="the_body_kyoto")
    loaded = state_mod._load()
    # the_body_kyoto removed from every section
    assert "the_body_kyoto" not in loaded["last_post"]
    assert "the_body_kyoto" not in loaded["recent_images"]
    # mybear_studio_kyoto still intact
    assert loaded["last_post"]["mybear_studio_kyoto"] == "2024-06-15"
    assert loaded["recent_images"]["mybear_studio_kyoto"] == ["img2"]


def test_run_reset_nonexistent_store_key_returns_empty_list(patch_state_file):
    _write_full_state(patch_state_file)
    result = run_reset("post-guard", store_key="does_not_exist")
    assert result["post_guard"] == []


def test_run_reset_empty_state_file_returns_empty_lists(patch_state_file):
    result = run_reset("post-guard")
    assert result["post_guard"] == []


# ---------------------------------------------------------------------------
# main() CLI integration tests
# ---------------------------------------------------------------------------

def test_main_post_guard_exits_0(patch_state_file, capsys):
    _write_full_state(patch_state_file)
    with pytest.raises(SystemExit) as exc:
        with patch("sys.argv", ["meo-reset", "post-guard"]):
            main()
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "Post guard" in out


def test_main_all_exits_0(patch_state_file, capsys):
    _write_full_state(patch_state_file)
    with pytest.raises(SystemExit) as exc:
        with patch("sys.argv", ["meo-reset", "all"]):
            main()
    assert exc.value.code == 0


def test_main_unknown_store_exits_1(patch_state_file, capsys):
    _write_full_state(patch_state_file)
    with pytest.raises(SystemExit) as exc:
        with patch("sys.argv", ["meo-reset", "post-guard", "--store", "bad_key"]):
            main()
    assert exc.value.code == 1
    assert "Unknown store key" in capsys.readouterr().err


def test_main_specific_store_shows_store_key_in_output(patch_state_file, capsys):
    _write_full_state(patch_state_file)
    with pytest.raises(SystemExit):
        with patch("sys.argv", ["meo-reset", "post-guard", "--store", "the_body_kyoto"]):
            main()
    out = capsys.readouterr().out
    assert "the_body_kyoto" in out


def test_main_nothing_to_clear_prints_message_and_exits_0(patch_state_file, capsys):
    """When state is empty, the CLI reports nothing to clear (not an error)."""
    with pytest.raises(SystemExit) as exc:
        with patch("sys.argv", ["meo-reset", "post-guard"]):
            main()
    assert exc.value.code == 0
    assert "Nothing to clear" in capsys.readouterr().out
