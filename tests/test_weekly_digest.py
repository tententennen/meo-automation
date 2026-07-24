"""Tests for meo.tools.weekly_digest — 7-day Slack summary."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from meo.tools.weekly_digest import (
    _filter_by_date,
    _format_digest,
    _format_star_line,
    _format_store_block,
    _format_theme_line,
    _send_to_slack,
    _week_range,
    run_weekly_digest,
    main,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

_STORES = [
    {"key": "the_body_kyoto", "name": "THE BODY 京都店", "industry": "beauty_salon"},
    {"key": "mybear_studio_kyoto", "name": "MYBEAR STUDIO 京都店", "industry": "fitness_studio"},
]

_POST_HISTORY = [
    {"date": "2026-07-17", "theme": "季節のお手入れ情報", "text": "冬の乾燥対策に。"},
    {"date": "2026-07-18", "theme": "キャンペーン", "text": "キャンペーン開催！"},
    {"date": "2026-07-19", "theme": "季節のお手入れ情報", "text": "乾燥が続きます。"},
    {"date": "2026-07-20", "theme": "スタッフ紹介", "text": "スタッフ紹介です。"},
    # outside window — should be excluded
    {"date": "2026-07-10", "theme": "古い投稿", "text": "先週の投稿。"},
    {"date": "2026-07-24", "theme": "今日の投稿", "text": "今日の投稿（除外）。"},
]

_REPLY_HISTORY = [
    {"date": "2026-07-17", "reviewer": "田中", "stars": "FIVE", "reply": "ありがとう！"},
    {"date": "2026-07-19", "reviewer": "鈴木", "stars": "FIVE", "reply": "またのご来店を！"},
    {"date": "2026-07-21", "reviewer": "佐藤", "stars": "THREE", "reply": "ご意見ありがとう。"},
    # outside window
    {"date": "2026-07-10", "reviewer": "古い", "stars": "ONE", "reply": "先週。"},
]

_START = date(2026, 7, 17)
_END = date(2026, 7, 23)


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.weekly_digest.cfg.store_list", lambda: list(_STORES))


# ---------------------------------------------------------------------------
# _week_range
# ---------------------------------------------------------------------------

def test_week_range_end_is_yesterday_in_jst():
    mock_now = datetime(2026, 7, 24, 0, 0, 0, tzinfo=timezone.utc)  # 9 AM JST
    with patch("meo.tools.weekly_digest.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now.astimezone(
            __import__("zoneinfo").ZoneInfo("Asia/Tokyo")
        )
        mock_dt.now.side_effect = lambda tz=None: (
            mock_now.astimezone(tz) if tz else mock_now
        )
        start, end = _week_range()
    assert end == date(2026, 7, 23)
    assert start == date(2026, 7, 17)
    assert (end - start).days == 6


# ---------------------------------------------------------------------------
# _filter_by_date
# ---------------------------------------------------------------------------

def test_filter_by_date_includes_entries_in_range():
    entries = [
        {"date": "2026-07-17", "text": "A"},
        {"date": "2026-07-20", "text": "B"},
        {"date": "2026-07-23", "text": "C"},
    ]
    result = _filter_by_date(entries, _START, _END)
    assert len(result) == 3


def test_filter_by_date_excludes_entries_before_start():
    entries = [{"date": "2026-07-16", "text": "old"}]
    assert _filter_by_date(entries, _START, _END) == []


def test_filter_by_date_excludes_entries_after_end():
    entries = [{"date": "2026-07-24", "text": "future"}]
    assert _filter_by_date(entries, _START, _END) == []


def test_filter_by_date_includes_boundary_dates():
    entries = [
        {"date": "2026-07-17", "text": "start boundary"},
        {"date": "2026-07-23", "text": "end boundary"},
    ]
    result = _filter_by_date(entries, _START, _END)
    assert len(result) == 2


def test_filter_by_date_skips_invalid_date_strings():
    entries = [
        {"date": "not-a-date", "text": "bad"},
        {"date": "", "text": "empty"},
        {"date": None, "text": "null"},
        {"text": "missing key"},
    ]
    assert _filter_by_date(entries, _START, _END) == []


def test_filter_by_date_empty_input_returns_empty():
    assert _filter_by_date([], _START, _END) == []


# ---------------------------------------------------------------------------
# _format_theme_line
# ---------------------------------------------------------------------------

def test_format_theme_line_empty_posts_returns_empty_string():
    assert _format_theme_line([]) == ""


def test_format_theme_line_posts_without_theme_key_returns_empty_string():
    posts = [{"date": "2026-07-17", "text": "no theme key"}]
    assert _format_theme_line(posts) == ""


def test_format_theme_line_single_theme():
    posts = [{"theme": "季節のお手入れ情報"}, {"theme": "季節のお手入れ情報"}]
    result = _format_theme_line(posts)
    assert "季節のお手入れ情報 ×2" in result
    assert result.startswith("  (")
    assert result.endswith(")")


def test_format_theme_line_multiple_themes_sorted_by_frequency():
    posts = [
        {"theme": "A"}, {"theme": "A"}, {"theme": "A"},
        {"theme": "B"}, {"theme": "B"},
        {"theme": "C"},
    ]
    result = _format_theme_line(posts)
    # A should appear before B, B before C
    assert result.index("A") < result.index("B") < result.index("C")


def test_format_theme_line_caps_at_top_themes():
    posts = [{"theme": f"テーマ{i}"} for i in range(10)]
    result = _format_theme_line(posts)
    # Only _TOP_THEMES=3 themes should appear → 3 "×" occurrences
    assert result.count("×") == 3


# ---------------------------------------------------------------------------
# _format_star_line
# ---------------------------------------------------------------------------

def test_format_star_line_empty_replies_returns_empty_string():
    assert _format_star_line([]) == ""


def test_format_star_line_single_five_star():
    replies = [{"stars": "FIVE"}, {"stars": "FIVE"}]
    result = _format_star_line(replies)
    assert "★★★★★ 2" in result
    assert result.startswith("  |  ")


def test_format_star_line_excludes_zero_count_ratings():
    replies = [{"stars": "FIVE"}, {"stars": "THREE"}]
    result = _format_star_line(replies)
    assert "★★★★☆" not in result  # FOUR was zero
    assert "★★★★★" in result
    assert "★★★☆☆" in result


def test_format_star_line_preserves_star_order():
    replies = [{"stars": "ONE"}, {"stars": "FIVE"}, {"stars": "THREE"}]
    result = _format_star_line(replies)
    assert result.index("★★★★★") < result.index("★★★☆☆") < result.index("★☆☆☆☆")


def test_format_star_line_unknown_rating_ignored():
    replies = [{"stars": "FIVE"}, {"stars": "UNKNOWN"}]
    result = _format_star_line(replies)
    assert "★★★★★ 1" in result
    # "UNKNOWN" should not appear in a readable format
    assert "UNKNOWN" not in result


# ---------------------------------------------------------------------------
# _format_store_block
# ---------------------------------------------------------------------------

def test_format_store_block_includes_store_name_and_key():
    store = {"key": "the_body_kyoto", "name": "THE BODY 京都店"}
    posts = [{"date": "2026-07-17", "theme": "テーマA", "text": "text"}]
    replies = [{"date": "2026-07-17", "stars": "FIVE", "reply": "reply"}]
    lines = _format_store_block(store, posts, replies)
    joined = "\n".join(lines)
    assert "THE BODY 京都店" in joined
    assert "the_body_kyoto" in joined


def test_format_store_block_shows_post_count():
    store = {"key": "k", "name": "N"}
    posts = [{"theme": "A"}] * 5
    lines = _format_store_block(store, posts, [])
    assert "5件" in "\n".join(lines)


def test_format_store_block_shows_reply_count():
    store = {"key": "k", "name": "N"}
    replies = [{"stars": "FIVE"}] * 3
    lines = _format_store_block(store, [], replies)
    assert "3件" in "\n".join(lines)


def test_format_store_block_zero_counts_when_empty():
    store = {"key": "k", "name": "N"}
    lines = _format_store_block(store, [], [])
    joined = "\n".join(lines)
    assert "投稿: 0件" in joined
    assert "返信: 0件" in joined


# ---------------------------------------------------------------------------
# _format_digest
# ---------------------------------------------------------------------------

def test_format_digest_includes_period_header():
    results = [(_STORES[0], [], [])]
    text = _format_digest(results, _START, _END)
    assert "2026-07-17" in text
    assert "2026-07-23" in text
    assert "週次サマリー" in text


def test_format_digest_includes_total_counts():
    posts = [{"date": "2026-07-17", "theme": "T", "text": "P"}] * 3
    replies = [{"date": "2026-07-17", "stars": "FIVE", "reply": "R"}] * 2
    results = [(_STORES[0], posts, replies), (_STORES[1], posts, replies)]
    text = _format_digest(results, _START, _END)
    assert "投稿 6件" in text
    assert "返信 4件" in text


def test_format_digest_all_zero_totals():
    results = [(_STORES[0], [], []), (_STORES[1], [], [])]
    text = _format_digest(results, _START, _END)
    assert "投稿 0件" in text
    assert "返信 0件" in text


def test_format_digest_includes_all_store_names():
    results = [(_STORES[0], [], []), (_STORES[1], [], [])]
    text = _format_digest(results, _START, _END)
    assert "THE BODY 京都店" in text
    assert "MYBEAR STUDIO 京都店" in text


# ---------------------------------------------------------------------------
# _send_to_slack
# ---------------------------------------------------------------------------

def test_send_to_slack_noop_when_no_webhook(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    with patch("meo.tools.weekly_digest.requests.post") as mock_post:
        _send_to_slack("test message")
    mock_post.assert_not_called()


def test_send_to_slack_posts_to_webhook(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("meo.tools.weekly_digest.requests.post", return_value=mock_resp) as mock_post:
        _send_to_slack("hello Slack")
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["text"] == "hello Slack"


def test_send_to_slack_logs_warning_on_error(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    with patch("meo.tools.weekly_digest.requests.post", side_effect=Exception("timeout")):
        with caplog.at_level(logging.WARNING, logger="meo.tools.weekly_digest"):
            _send_to_slack("will fail")
    assert any("digest Slack send failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# run_weekly_digest
# ---------------------------------------------------------------------------

@pytest.fixture()
def _patch_history(monkeypatch):
    in_window_posts = [e for e in _POST_HISTORY if e["date"] >= "2026-07-17" and e["date"] <= "2026-07-23"]
    in_window_replies = [e for e in _REPLY_HISTORY if e["date"] >= "2026-07-17" and e["date"] <= "2026-07-23"]

    monkeypatch.setattr(
        "meo.tools.weekly_digest.get_post_history",
        lambda key: list(_POST_HISTORY) if key == "the_body_kyoto" else [],
    )
    monkeypatch.setattr(
        "meo.tools.weekly_digest.get_reply_history",
        lambda key: list(_REPLY_HISTORY) if key == "the_body_kyoto" else [],
    )


def test_run_weekly_digest_dry_run_does_not_send_to_slack(_patch_history, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    # Patch week range to a fixed window that matches our fixture data
    with patch("meo.tools.weekly_digest._week_range", return_value=(_START, _END)):
        with patch("meo.tools.weekly_digest.requests.post") as mock_post:
            result = run_weekly_digest(dry_run=True)
    mock_post.assert_not_called()
    assert isinstance(result, str)
    assert len(result) > 0


def test_run_weekly_digest_live_sends_to_slack(_patch_history, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("meo.tools.weekly_digest._week_range", return_value=(_START, _END)):
        with patch("meo.tools.weekly_digest.requests.post", return_value=mock_resp) as mock_post:
            result = run_weekly_digest(dry_run=False)
    mock_post.assert_called_once()
    assert "週次サマリー" in result


def test_run_weekly_digest_filters_history_to_window(_patch_history):
    with patch("meo.tools.weekly_digest._week_range", return_value=(_START, _END)):
        text = run_weekly_digest(dry_run=True)
    # The fixture has 4 in-window posts for the_body_kyoto and 2 for mybear (0)
    # Total across 2 stores = 4 + 0 = 4
    assert "投稿 4件" in text


def test_run_weekly_digest_returns_string_with_period(_patch_history):
    with patch("meo.tools.weekly_digest._week_range", return_value=(_START, _END)):
        text = run_weekly_digest(dry_run=True)
    assert "2026-07-17" in text
    assert "2026-07-23" in text


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def test_main_dry_run_prints_digest_to_stdout(_patch_history, capsys):
    with patch("meo.tools.weekly_digest._week_range", return_value=(_START, _END)):
        with patch("sys.argv", ["meo-weekly-digest", "--dry-run"]):
            main()
    captured = capsys.readouterr()
    assert "週次サマリー" in captured.out


def test_main_live_run_prints_and_sends(_patch_history, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("meo.tools.weekly_digest._week_range", return_value=(_START, _END)):
        with patch("meo.tools.weekly_digest.requests.post", return_value=mock_resp) as mock_post:
            with patch("sys.argv", ["meo-weekly-digest"]):
                main()
    captured = capsys.readouterr()
    assert "週次サマリー" in captured.out
    mock_post.assert_called_once()


def test_main_dry_run_does_not_send(_patch_history, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    with patch("meo.tools.weekly_digest._week_range", return_value=(_START, _END)):
        with patch("meo.tools.weekly_digest.requests.post") as mock_post:
            with patch("sys.argv", ["meo-weekly-digest", "--dry-run"]):
                main()
    mock_post.assert_not_called()
