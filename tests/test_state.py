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


# ---------------------------------------------------------------------------
# Theme rotation tests
# ---------------------------------------------------------------------------

def test_get_recent_themes_empty_when_no_history():
    assert state_mod.get_recent_themes("my_store") == []


def test_record_theme_persists_and_is_retrievable():
    state_mod.record_theme("my_store", "季節のお手入れ情報")
    assert state_mod.get_recent_themes("my_store") == ["季節のお手入れ情報"]


def test_record_theme_most_recent_is_first():
    state_mod.record_theme("my_store", "スタッフ紹介")
    state_mod.record_theme("my_store", "新メニュー・クラス紹介")
    recent = state_mod.get_recent_themes("my_store")
    assert recent[0] == "新メニュー・クラス紹介"
    assert recent[1] == "スタッフ紹介"


def test_record_theme_history_capped_at_limit():
    limit = state_mod._THEME_HISTORY_SIZE
    for i in range(limit + 2):
        state_mod.record_theme("my_store", f"テーマ_{i}")
    recent = state_mod.get_recent_themes("my_store")
    assert len(recent) == limit
    assert recent[0] == f"テーマ_{limit + 1}"


def test_record_theme_deduplicates_on_reuse():
    state_mod.record_theme("my_store", "テーマA")
    state_mod.record_theme("my_store", "テーマB")
    state_mod.record_theme("my_store", "テーマA")  # re-use A
    recent = state_mod.get_recent_themes("my_store")
    assert recent[0] == "テーマA"
    assert recent.count("テーマA") == 1


def test_theme_history_independent_per_store():
    state_mod.record_theme("store_a", "テーマX")
    assert state_mod.get_recent_themes("store_b") == []


# ---------------------------------------------------------------------------
# Post content archiving tests
# ---------------------------------------------------------------------------

def test_get_post_history_empty_when_no_history():
    assert state_mod.get_post_history("my_store") == []


def test_record_post_content_stores_entry(frozen_today):
    state_mod.record_post_content("my_store", "テスト投稿テキスト", "季節テーマ", "accounts/1/localPosts/9")
    history = state_mod.get_post_history("my_store")
    assert len(history) == 1
    entry = history[0]
    assert entry["date"] == _FIXED_TODAY.isoformat()
    assert entry["theme"] == "季節テーマ"
    assert entry["text"] == "テスト投稿テキスト"
    assert entry["post_name"] == "accounts/1/localPosts/9"


def test_record_post_content_most_recent_first(frozen_today):
    state_mod.record_post_content("my_store", "first post", "テーマ1")
    state_mod.record_post_content("my_store", "second post", "テーマ2")
    history = state_mod.get_post_history("my_store")
    assert history[0]["text"] == "second post"
    assert history[1]["text"] == "first post"


def test_record_post_content_capped_at_limit(frozen_today):
    limit = state_mod._POST_HISTORY_SIZE
    for i in range(limit + 3):
        state_mod.record_post_content("my_store", f"post {i}", f"theme {i}")
    history = state_mod.get_post_history("my_store")
    assert len(history) == limit
    assert history[0]["text"] == f"post {limit + 2}"


def test_post_history_independent_per_store(frozen_today):
    state_mod.record_post_content("store_a", "A post", "テーマA")
    assert state_mod.get_post_history("store_b") == []


def test_record_post_content_none_theme_stored_as_empty_string(frozen_today):
    state_mod.record_post_content("my_store", "no theme post", None)
    history = state_mod.get_post_history("my_store")
    assert history[0]["theme"] == ""


# ---------------------------------------------------------------------------
# Reply content archiving tests
# ---------------------------------------------------------------------------

def test_get_reply_history_empty_when_no_history():
    assert state_mod.get_reply_history("my_store") == []


def test_record_reply_content_stores_entry(frozen_today):
    state_mod.record_reply_content("my_store", "rev001", "田中太郎", "FIVE", "ありがとうございます！")
    history = state_mod.get_reply_history("my_store")
    assert len(history) == 1
    entry = history[0]
    assert entry["date"] == _FIXED_TODAY.isoformat()
    assert entry["review_id"] == "rev001"
    assert entry["reviewer"] == "田中太郎"
    assert entry["stars"] == "FIVE"
    assert entry["reply"] == "ありがとうございます！"


def test_record_reply_content_most_recent_first(frozen_today):
    state_mod.record_reply_content("my_store", "rev001", "A", "FOUR", "reply 1")
    state_mod.record_reply_content("my_store", "rev002", "B", "FIVE", "reply 2")
    history = state_mod.get_reply_history("my_store")
    assert history[0]["review_id"] == "rev002"
    assert history[1]["review_id"] == "rev001"


def test_record_reply_content_capped_at_limit(frozen_today):
    limit = state_mod._REPLY_HISTORY_SIZE
    for i in range(limit + 3):
        state_mod.record_reply_content("my_store", f"rev{i:03d}", "X", "THREE", f"reply {i}")
    history = state_mod.get_reply_history("my_store")
    assert len(history) == limit
    assert history[0]["review_id"] == f"rev{limit + 2:03d}"


def test_reply_history_independent_per_store(frozen_today):
    state_mod.record_reply_content("store_a", "rev001", "A", "FIVE", "reply")
    assert state_mod.get_reply_history("store_b") == []


# ---------------------------------------------------------------------------
# Replied review tracking tests (duplicate-reply guard)
# ---------------------------------------------------------------------------

def test_get_replied_reviews_empty_when_no_history():
    assert state_mod.get_replied_reviews("my_store") == []


def test_record_replied_review_persists_and_is_retrievable():
    state_mod.record_replied_review("my_store", "rev001")
    assert state_mod.get_replied_reviews("my_store") == ["rev001"]


def test_record_replied_review_most_recent_is_first():
    state_mod.record_replied_review("my_store", "rev001")
    state_mod.record_replied_review("my_store", "rev002")
    ids = state_mod.get_replied_reviews("my_store")
    assert ids[0] == "rev002"
    assert ids[1] == "rev001"


def test_record_replied_review_capped_at_capacity(monkeypatch):
    monkeypatch.setattr(state_mod, "_REPLIED_REVIEW_CAPACITY", 3)
    for i in range(5):
        state_mod.record_replied_review("my_store", f"rev{i:03d}")
    ids = state_mod.get_replied_reviews("my_store")
    assert len(ids) == 3
    assert ids[0] == "rev004"


def test_record_replied_review_deduplicates_on_reuse():
    state_mod.record_replied_review("my_store", "rev_A")
    state_mod.record_replied_review("my_store", "rev_B")
    state_mod.record_replied_review("my_store", "rev_A")  # re-record A
    ids = state_mod.get_replied_reviews("my_store")
    assert ids[0] == "rev_A"
    assert ids.count("rev_A") == 1


def test_replied_review_history_independent_per_store():
    state_mod.record_replied_review("store_a", "rev001")
    assert state_mod.get_replied_reviews("store_b") == []


# ---------------------------------------------------------------------------
# State reset helper tests (clear_* functions)
# ---------------------------------------------------------------------------

def test_clear_post_guard_specific_store(frozen_today):
    state_mod.record_post("store_a")
    state_mod.record_post("store_b")
    cleared = state_mod.clear_post_guard("store_a")
    assert cleared == ["store_a"]
    assert state_mod.should_post_today("store_a") is True
    assert state_mod.should_post_today("store_b") is False  # untouched


def test_clear_post_guard_all_stores(frozen_today):
    state_mod.record_post("store_a")
    state_mod.record_post("store_b")
    cleared = state_mod.clear_post_guard()
    assert set(cleared) == {"store_a", "store_b"}
    assert state_mod.should_post_today("store_a") is True
    assert state_mod.should_post_today("store_b") is True


def test_clear_post_guard_missing_store_returns_empty():
    cleared = state_mod.clear_post_guard("nonexistent_store")
    assert cleared == []


def test_clear_image_history_specific_store():
    state_mod.record_image("store_a", "img1")
    state_mod.record_image("store_b", "img2")
    cleared = state_mod.clear_image_history("store_a")
    assert cleared == ["store_a"]
    assert state_mod.get_recent_images("store_a") == []
    assert state_mod.get_recent_images("store_b") == ["img2"]  # untouched


def test_clear_image_history_all_stores():
    state_mod.record_image("store_a", "img1")
    state_mod.record_image("store_b", "img2")
    cleared = state_mod.clear_image_history()
    assert set(cleared) == {"store_a", "store_b"}
    assert state_mod.get_recent_images("store_a") == []
    assert state_mod.get_recent_images("store_b") == []


def test_clear_theme_history_specific_store():
    state_mod.record_theme("store_a", "テーマA")
    state_mod.record_theme("store_b", "テーマB")
    cleared = state_mod.clear_theme_history("store_a")
    assert cleared == ["store_a"]
    assert state_mod.get_recent_themes("store_a") == []
    assert state_mod.get_recent_themes("store_b") == ["テーマB"]  # untouched


def test_clear_theme_history_all_stores():
    state_mod.record_theme("store_a", "テーマA")
    state_mod.record_theme("store_b", "テーマB")
    cleared = state_mod.clear_theme_history()
    assert set(cleared) == {"store_a", "store_b"}
    assert state_mod.get_recent_themes("store_a") == []
    assert state_mod.get_recent_themes("store_b") == []


def test_clear_replied_reviews_specific_store():
    state_mod.record_replied_review("store_a", "rev1")
    state_mod.record_replied_review("store_b", "rev2")
    cleared = state_mod.clear_replied_reviews("store_a")
    assert cleared == ["store_a"]
    assert state_mod.get_replied_reviews("store_a") == []
    assert state_mod.get_replied_reviews("store_b") == ["rev2"]  # untouched


def test_clear_replied_reviews_all_stores():
    state_mod.record_replied_review("store_a", "rev1")
    state_mod.record_replied_review("store_b", "rev2")
    cleared = state_mod.clear_replied_reviews()
    assert set(cleared) == {"store_a", "store_b"}
    assert state_mod.get_replied_reviews("store_a") == []
    assert state_mod.get_replied_reviews("store_b") == []
