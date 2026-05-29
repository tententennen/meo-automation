"""Tests for per-store post deduplication state."""

import json
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

import meo.state as state_mod

_FIXED_TODAY = date(2024, 6, 15)


def _write_state(tmp_path: Path, data: dict) -> Path:
    f = tmp_path / "state.json"
    f.write_text(json.dumps(data))
    return f


@pytest.fixture(autouse=True)
def patch_state_file(tmp_path, monkeypatch):
    """Redirect the state file to a temp directory for every test."""
    state_file = tmp_path / "state.json"
    monkeypatch.setattr(state_mod, "_STATE_FILE", state_file)
    return state_file


@pytest.fixture
def frozen_today(monkeypatch):
    """Freeze _today() to a fixed date for deterministic timezone-sensitive tests."""
    monkeypatch.setattr(state_mod, "_today", lambda: _FIXED_TODAY)
    return _FIXED_TODAY


def test_no_state_file_means_post_due():
    assert state_mod.should_post_today("my_store") is True


def test_post_today_means_not_due(frozen_today):
    state_mod.record_post("my_store")
    assert state_mod.should_post_today("my_store") is False


def test_post_yesterday_with_cadence_1_is_due(frozen_today):
    yesterday = (frozen_today - timedelta(days=1)).isoformat()
    state_mod._STATE_FILE.write_text(
        json.dumps({"last_post": {"my_store": yesterday}})
    )
    assert state_mod.should_post_today("my_store", cadence_days=1) is True


def test_post_yesterday_with_cadence_2_not_due(frozen_today):
    yesterday = (frozen_today - timedelta(days=1)).isoformat()
    state_mod._STATE_FILE.write_text(
        json.dumps({"last_post": {"my_store": yesterday}})
    )
    assert state_mod.should_post_today("my_store", cadence_days=2) is False


def test_different_store_keys_tracked_independently(frozen_today):
    state_mod.record_post("store_a")
    assert state_mod.should_post_today("store_a") is False
    assert state_mod.should_post_today("store_b") is True


def test_corrupt_state_falls_back_to_post_due():
    state_mod._STATE_FILE.write_text("not valid json{{{")
    assert state_mod.should_post_today("my_store") is True


def test_invalid_date_string_falls_back_to_post_due():
    state_mod._STATE_FILE.write_text(
        json.dumps({"last_post": {"my_store": "not-a-date"}})
    )
    assert state_mod.should_post_today("my_store") is True


def test_record_post_persists_today(frozen_today):
    state_mod.record_post("store_x")
    raw = json.loads(state_mod._STATE_FILE.read_text())
    assert raw["last_post"]["store_x"] == _FIXED_TODAY.isoformat()


# ---------------------------------------------------------------------------
# Image rotation tests
# ---------------------------------------------------------------------------

def test_get_recent_images_empty_when_no_history():
    assert state_mod.get_recent_images("my_store") == []


def test_record_image_persists_and_is_retrievable():
    state_mod.record_image("my_store", "file_abc")
    assert state_mod.get_recent_images("my_store") == ["file_abc"]


def test_record_image_most_recent_is_first():
    state_mod.record_image("my_store", "file_001")
    state_mod.record_image("my_store", "file_002")
    recent = state_mod.get_recent_images("my_store")
    assert recent[0] == "file_002"
    assert recent[1] == "file_001"


def test_record_image_history_capped_at_limit():
    limit = state_mod._IMAGE_HISTORY_SIZE
    for i in range(limit + 3):
        state_mod.record_image("my_store", f"file_{i:03d}")
    recent = state_mod.get_recent_images("my_store")
    assert len(recent) == limit
    assert recent[0] == f"file_{limit + 2:03d}"


def test_record_image_deduplicates_on_reuse():
    state_mod.record_image("my_store", "file_A")
    state_mod.record_image("my_store", "file_B")
    state_mod.record_image("my_store", "file_A")  # re-use A
    recent = state_mod.get_recent_images("my_store")
    assert recent[0] == "file_A"
    assert recent.count("file_A") == 1


def test_image_history_independent_per_store():
    state_mod.record_image("store_a", "file_X")
    assert state_mod.get_recent_images("store_b") == []
