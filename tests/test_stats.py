"""Tests for meo.tools.stats — aggregate statistics view."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from unittest.mock import patch

import pytest

from meo.tools.stats import (
    _bar,
    _date_range,
    _posts_per_week,
    run_stats,
    main,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STORES = [
    {"key": "the_body_kyoto", "name": "THE BODY 京都店", "industry": "beauty_salon"},
    {"key": "mybear_studio_kyoto", "name": "MYBEAR STUDIO 京都店", "industry": "fitness_studio"},
]

_POST_HISTORY = [
    {"date": "2026-01-01", "theme": "季節のお手入れ情報", "text": "冬の乾燥対策に。"},
    {"date": "2026-01-08", "theme": "キャンペーン・お得情報", "text": "新年キャンペーン！"},
    {"date": "2026-01-15", "theme": "季節のお手入れ情報", "text": "乾燥が続く季節。"},
    {"date": "2026-01-22", "theme": "スタッフ紹介・こだわりのご紹介", "text": "スタッフ山田です。"},
    {"date": "2026-01-29", "theme": "季節のお手入れ情報", "text": "春が近づいてきました。"},
]

_REPLY_HISTORY = [
    {"date": "2026-01-05", "reviewer": "田中", "stars": "FIVE", "reply": "ありがとう！"},
    {"date": "2026-01-12", "reviewer": "鈴木", "stars": "FIVE", "reply": "またのご来店を！"},
    {"date": "2026-01-19", "reviewer": "佐藤", "stars": "THREE", "reply": "ご意見ありがとう。"},
    {"date": "2026-01-26", "reviewer": "山田", "stars": "FOUR", "reply": "嬉しいです！"},
]


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.stats.cfg.store_list", lambda: list(_STORES))


@pytest.fixture()
def _patch_history_kyoto(monkeypatch):
    def _posts(key):
        return list(_POST_HISTORY) if key == "the_body_kyoto" else []

    def _replies(key):
        return list(_REPLY_HISTORY) if key == "the_body_kyoto" else []

    monkeypatch.setattr("meo.tools.stats.get_post_history", _posts)
    monkeypatch.setattr("meo.tools.stats.get_reply_history", _replies)


@pytest.fixture()
def _patch_empty_history(monkeypatch):
    monkeypatch.setattr("meo.tools.stats.get_post_history", lambda key: [])
    monkeypatch.setattr("meo.tools.stats.get_reply_history", lambda key: [])


# ---------------------------------------------------------------------------
# Unit tests — helper functions
# ---------------------------------------------------------------------------

def test_date_range_returns_min_max():
    entries = [
        {"date": "2026-03-10"},
        {"date": "2026-01-01"},
        {"date": "2026-07-22"},
    ]
    assert _date_range(entries) == ("2026-01-01", "2026-07-22")


def test_date_range_single_entry():
    assert _date_range([{"date": "2026-05-01"}]) == ("2026-05-01", "2026-05-01")


def test_date_range_empty_returns_none():
    assert _date_range([]) is None


def test_date_range_skips_missing_date():
    entries = [{"theme": "no date"}, {"date": "2026-06-01"}]
    assert _date_range(entries) == ("2026-06-01", "2026-06-01")


def test_date_range_all_missing_dates_returns_none():
    assert _date_range([{"theme": "no date"}, {"theme": "also no date"}]) is None


def test_posts_per_week_7_days():
    # 1 post over exactly 7 days = 1.0/week
    assert _posts_per_week("2026-01-01", "2026-01-08", 1) == "~1.0/week"


def test_posts_per_week_28_days_4_posts():
    # 4 posts over 28 days = 1.0/week
    assert _posts_per_week("2026-01-01", "2026-01-29", 4) == "~1.0/week"


def test_posts_per_week_same_date_does_not_divide_by_zero():
    # same first and last date → days clamps to 1 → no ZeroDivisionError
    result = _posts_per_week("2026-01-01", "2026-01-01", 1)
    assert result.startswith("~")


def test_posts_per_week_invalid_date_returns_empty():
    assert _posts_per_week("not-a-date", "2026-01-01", 5) == ""


def test_bar_full():
    assert _bar(12, 12) == "█" * 12


def test_bar_half():
    result = _bar(6, 12)
    assert result == "█" * 6


def test_bar_zero_count():
    assert _bar(0, 10) == ""


def test_bar_zero_total():
    assert _bar(0, 0) == ""


def test_bar_rounds_proportionally():
    # 1/4 of 12 = 3 filled characters
    assert _bar(1, 4) == "█" * 3


# ---------------------------------------------------------------------------
# run_stats() integration tests
# ---------------------------------------------------------------------------

def test_run_stats_returns_zero_exit_code(_patch_history_kyoto):
    _, code = run_stats()
    assert code == 0


def test_run_stats_includes_all_store_names(_patch_history_kyoto):
    text, _ = run_stats()
    assert "THE BODY 京都店" in text
    assert "MYBEAR STUDIO 京都店" in text


def test_run_stats_shows_post_total(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    assert "5" in text  # 5 posts in _POST_HISTORY


def test_run_stats_shows_reply_total(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    assert "4" in text  # 4 replies in _REPLY_HISTORY


def test_run_stats_shows_top_theme(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    # "季節のお手入れ情報" appears 3× — should be the top theme
    assert "季節のお手入れ情報" in text
    assert "3×" in text


def test_run_stats_shows_star_ratings(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    assert "★★★★★" in text
    assert "★★★☆☆" in text


def test_run_stats_shows_date_period(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    assert "2026-01-01" in text
    assert "2026-01-29" in text


def test_run_stats_shows_rate(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    # 5 posts over 28 days ≈ 1.3/week
    assert "/week" in text


def test_run_stats_empty_history_shows_placeholder(_patch_empty_history):
    text, code = run_stats()
    assert code == 0
    assert "no posts archived yet" in text
    assert "no replies archived yet" in text


def test_run_stats_unknown_store_returns_error(_patch_empty_history):
    text, code = run_stats(store_filter="nonexistent_store")
    assert code == 1
    assert "Unknown store key" in text


def test_run_stats_filter_shows_only_that_store(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    assert "THE BODY 京都店" in text
    assert "MYBEAR STUDIO 京都店" not in text


def test_run_stats_header_includes_jst_timestamp(_patch_empty_history):
    from zoneinfo import ZoneInfo
    # 2026-07-23 00:00 UTC = 09:00 JST
    utc_midnight = datetime(2026, 7, 23, 0, 0, 0, tzinfo=timezone.utc)
    jst = ZoneInfo("Asia/Tokyo")
    jst_9am = utc_midnight.astimezone(jst)

    with patch("meo.tools.stats.datetime") as mock_dt:
        mock_dt.now.return_value = jst_9am
        text, _ = run_stats()

    assert "2026-07-23 09:00 JST" in text


def test_run_stats_shows_store_key(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    assert "the_body_kyoto" in text


def test_run_stats_all_star_ratings_in_distribution(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    # All 5 star levels should appear in distribution
    for label in ["★★★★★", "★★★★☆", "★★★☆☆", "★★☆☆☆", "★☆☆☆☆"]:
        assert label in text


def test_run_stats_percentage_shown(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    # 2/4 = 50% for FIVE stars
    assert "50%" in text


def test_run_stats_zero_star_count_shows_zero(_patch_history_kyoto):
    text, _ = run_stats(store_filter="the_body_kyoto")
    # ONE-star has 0 replies
    assert "  0  " in text


# ---------------------------------------------------------------------------
# main() CLI tests
# ---------------------------------------------------------------------------

def test_main_exits_zero(_patch_empty_history, capsys):
    with patch("sys.argv", ["meo-stats"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0


def test_main_with_valid_store_exits_zero(_patch_history_kyoto, capsys):
    with patch("sys.argv", ["meo-stats", "--store", "the_body_kyoto"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 0


def test_main_with_unknown_store_exits_one(_patch_empty_history, capsys):
    with patch("sys.argv", ["meo-stats", "--store", "no_such_store"]):
        with pytest.raises(SystemExit) as exc:
            main()
    assert exc.value.code == 1


def test_main_prints_to_stdout(_patch_history_kyoto, capsys):
    with patch("sys.argv", ["meo-stats"]):
        with pytest.raises(SystemExit):
            main()
    captured = capsys.readouterr()
    assert "MEO Automation" in captured.out
    assert "THE BODY 京都店" in captured.out


def test_run_stats_handles_malformed_date_in_post_history(monkeypatch):
    """_format_store_section should not crash when state.json has a bad ISO date.

    _date_range() returns the raw string; date.fromisoformat() then raises
    ValueError inside the try/except guard (lines 97-98 in stats.py).
    The output must still include the store section and report the total.
    """
    monkeypatch.setattr("meo.tools.stats.cfg.store_list", lambda: list(_STORES))
    monkeypatch.setattr(
        "meo.tools.stats.get_post_history",
        lambda key: [{"date": "not-a-date", "theme": "テーマ", "text": "テキスト"}]
        if key == "the_body_kyoto"
        else [],
    )
    monkeypatch.setattr("meo.tools.stats.get_reply_history", lambda key: [])

    text, code = run_stats(store_filter="the_body_kyoto")
    assert code == 0
    assert "Total archived:" in text
