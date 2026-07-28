"""Tests for meo.tools.monthly_digest — previous-month Slack summary."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from meo.tools.monthly_digest import (
    _filter_by_date,
    _format_digest,
    _format_star_line,
    _format_store_block,
    _format_theme_line,
    _month_label,
    _month_range,
    _send_to_slack,
    run_monthly_digest,
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
    {"date": "2026-07-01", "theme": "季節のお手入れ情報", "text": "夏の肌ケア。"},
    {"date": "2026-07-10", "theme": "キャンペーン", "text": "夏のキャンペーン！"},
    {"date": "2026-07-15", "theme": "スタッフ紹介", "text": "スタッフ紹介。"},
    {"date": "2026-07-20", "theme": "季節のお手入れ情報", "text": "紫外線対策。"},
    {"date": "2026-07-31", "theme": "キャンペーン", "text": "月末キャンペーン！"},
    # outside window — should be excluded
    {"date": "2026-06-30", "theme": "6月末", "text": "先月の投稿。"},
    {"date": "2026-08-01", "theme": "8月始め", "text": "来月の投稿。"},
]

_REPLY_HISTORY = [
    {"date": "2026-07-05", "reviewer": "田中", "stars": "FIVE", "reply": "ありがとう！"},
    {"date": "2026-07-12", "reviewer": "鈴木", "stars": "FIVE", "reply": "またのご来店を！"},
    {"date": "2026-07-18", "reviewer": "佐藤", "stars": "THREE", "reply": "ご意見ありがとう。"},
    {"date": "2026-07-25", "reviewer": "山田", "stars": "ONE", "reply": "大変申し訳ありません。"},
    # outside window
    {"date": "2026-06-30", "reviewer": "古い", "stars": "FOUR", "reply": "先月。"},
    {"date": "2026-08-01", "reviewer": "新しい", "stars": "FIVE", "reply": "来月。"},
]

_START = date(2026, 7, 1)
_END = date(2026, 7, 31)


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.monthly_digest.cfg.store_list", lambda: list(_STORES))


# ---------------------------------------------------------------------------
# _month_range
# ---------------------------------------------------------------------------

def test_month_range_on_first_of_month_returns_previous_month():
    # Aug 1 JST → July 1-31
    mock_now = datetime(2026, 8, 1, 0, 0, 0).astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Tokyo")
    )
    with patch("meo.tools.monthly_digest.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        start, end = _month_range()
    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)


def test_month_range_mid_month_still_returns_previous_full_month():
    # Aug 15 JST → still July 1-31
    mock_now = datetime(2026, 8, 15, 10, 0, 0).astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Tokyo")
    )
    with patch("meo.tools.monthly_digest.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        start, end = _month_range()
    assert start == date(2026, 7, 1)
    assert end == date(2026, 7, 31)


def test_month_range_january_wraps_to_previous_year_december():
    # Jan 1, 2027 → December 2026
    mock_now = datetime(2027, 1, 1, 0, 0, 0).astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Tokyo")
    )
    with patch("meo.tools.monthly_digest.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        start, end = _month_range()
    assert start == date(2026, 12, 1)
    assert end == date(2026, 12, 31)


def test_month_range_march_returns_february_end_correctly():
    # Mar 1, 2027 → Feb 1-28, 2027 (not a leap year)
    mock_now = datetime(2027, 3, 1, 0, 0, 0).astimezone(
        __import__("zoneinfo").ZoneInfo("Asia/Tokyo")
    )
    with patch("meo.tools.monthly_digest.datetime") as mock_dt:
        mock_dt.now.return_value = mock_now
        start, end = _month_range()
    assert start == date(2027, 2, 1)
    assert end == date(2027, 2, 28)


# ---------------------------------------------------------------------------
# _month_label
# ---------------------------------------------------------------------------

def test_month_label_july():
    assert _month_label(date(2026, 7, 1)) == "2026年7月"


def test_month_label_january():
    assert _month_label(date(2026, 1, 1)) == "2026年1月"


def test_month_label_december():
    assert _month_label(date(2025, 12, 1)) == "2025年12月"


def test_month_label_includes_year():
    label = _month_label(date(2027, 4, 1))
    assert "2027" in label
    assert "4月" in label


# ---------------------------------------------------------------------------
# _filter_by_date
# ---------------------------------------------------------------------------

def test_filter_by_date_includes_entries_in_range():
    entries = [
        {"date": "2026-07-01", "text": "A"},
        {"date": "2026-07-15", "text": "B"},
        {"date": "2026-07-31", "text": "C"},
    ]
    result = _filter_by_date(entries, _START, _END)
    assert len(result) == 3


def test_filter_by_date_excludes_entries_before_start():
    entries = [{"date": "2026-06-30", "text": "old"}]
    assert _filter_by_date(entries, _START, _END) == []


def test_filter_by_date_excludes_entries_after_end():
    entries = [{"date": "2026-08-01", "text": "future"}]
    assert _filter_by_date(entries, _START, _END) == []


def test_filter_by_date_includes_boundary_dates():
    entries = [
        {"date": "2026-07-01", "text": "first day"},
        {"date": "2026-07-31", "text": "last day"},
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
    posts = [{"date": "2026-07-01", "text": "no theme key"}]
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
    assert result.index("A") < result.index("B") < result.index("C")


def test_format_theme_line_caps_at_top_themes_five():
    # monthly digest uses _TOP_THEMES=5
    posts = [{"theme": f"テーマ{i}"} for i in range(10)]
    result = _format_theme_line(posts)
    assert result.count("×") == 5


# ---------------------------------------------------------------------------
# _format_star_line
# ---------------------------------------------------------------------------

def test_format_star_line_empty_replies_returns_empty_string():
    assert _format_star_line([]) == ""


def test_format_star_line_shows_all_five_ratings_including_zeros():
    # Unlike weekly digest, monthly shows all 5 star levels.
    replies = [{"stars": "FIVE"}, {"stars": "THREE"}]
    result = _format_star_line(replies)
    assert "★★★★★ 1" in result
    assert "★★★★☆ 0" in result   # FOUR was zero — still shown
    assert "★★★☆☆ 1" in result
    assert "★★☆☆☆ 0" in result   # TWO was zero — still shown
    assert "★☆☆☆☆ 0" in result   # ONE was zero — still shown


def test_format_star_line_starts_with_pipe_separator():
    replies = [{"stars": "FIVE"}]
    assert _format_star_line(replies).startswith("  |  ")


def test_format_star_line_preserves_high_to_low_order():
    replies = [{"stars": "ONE"}, {"stars": "FIVE"}, {"stars": "THREE"}]
    result = _format_star_line(replies)
    assert result.index("★★★★★") < result.index("★★★☆☆") < result.index("★☆☆☆☆")


def test_format_star_line_counts_correctly():
    replies = [
        {"stars": "FIVE"}, {"stars": "FIVE"}, {"stars": "FIVE"},
        {"stars": "FOUR"},
    ]
    result = _format_star_line(replies)
    assert "★★★★★ 3" in result
    assert "★★★★☆ 1" in result
    assert "★★★☆☆ 0" in result


# ---------------------------------------------------------------------------
# _format_store_block
# ---------------------------------------------------------------------------

def test_format_store_block_includes_store_name_and_key():
    store = {"key": "the_body_kyoto", "name": "THE BODY 京都店"}
    posts = [{"date": "2026-07-01", "theme": "テーマA", "text": "text"}]
    replies = [{"date": "2026-07-01", "stars": "FIVE", "reply": "reply"}]
    lines = _format_store_block(store, posts, replies)
    joined = "\n".join(lines)
    assert "THE BODY 京都店" in joined
    assert "the_body_kyoto" in joined


def test_format_store_block_shows_post_count():
    store = {"key": "k", "name": "N"}
    posts = [{"theme": "A"}] * 21
    lines = _format_store_block(store, posts, [])
    assert "21件" in "\n".join(lines)


def test_format_store_block_shows_reply_count():
    store = {"key": "k", "name": "N"}
    replies = [{"stars": "FIVE"}] * 18
    lines = _format_store_block(store, [], replies)
    assert "18件" in "\n".join(lines)


def test_format_store_block_zero_counts_when_empty():
    store = {"key": "k", "name": "N"}
    lines = _format_store_block(store, [], [])
    joined = "\n".join(lines)
    assert "投稿: 0件" in joined
    assert "返信: 0件" in joined


# ---------------------------------------------------------------------------
# _format_digest
# ---------------------------------------------------------------------------

def test_format_digest_includes_month_label_in_header():
    results = [(_STORES[0], [], [])]
    text = _format_digest(results, _START, _END)
    assert "月次サマリー" in text
    assert "2026年7月" in text


def test_format_digest_includes_total_counts():
    posts = [{"date": "2026-07-01", "theme": "T", "text": "P"}] * 15
    replies = [{"date": "2026-07-01", "stars": "FIVE", "reply": "R"}] * 10
    results = [(_STORES[0], posts, replies), (_STORES[1], posts, replies)]
    text = _format_digest(results, _START, _END)
    assert "投稿 30件" in text
    assert "返信 20件" in text


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


def test_format_digest_header_uses_month_label_not_date_range():
    results = [(_STORES[0], [], [])]
    text = _format_digest(results, _START, _END)
    # Monthly digest uses "2026年7月" not "2026-07-01 〜 2026-07-31"
    assert "2026年7月" in text
    assert "〜" not in text


# ---------------------------------------------------------------------------
# _send_to_slack
# ---------------------------------------------------------------------------

def test_send_to_slack_noop_when_no_webhook(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    with patch("meo.tools.monthly_digest.requests.post") as mock_post:
        _send_to_slack("test message")
    mock_post.assert_not_called()


def test_send_to_slack_posts_to_webhook(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("meo.tools.monthly_digest.requests.post", return_value=mock_resp) as mock_post:
        _send_to_slack("hello Slack")
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs[1]["json"]["text"] == "hello Slack"


def test_send_to_slack_logs_warning_on_error(monkeypatch, caplog):
    import logging
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    with patch("meo.tools.monthly_digest.requests.post", side_effect=Exception("timeout")):
        with caplog.at_level(logging.WARNING, logger="meo.tools.monthly_digest"):
            _send_to_slack("will fail")
    assert any("Monthly digest Slack send failed" in r.message for r in caplog.records)


def test_send_to_slack_http_error_logs_warning(monkeypatch, caplog):
    import logging
    import requests as req_module
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = req_module.HTTPError("500 Server Error")
    with patch("meo.tools.monthly_digest.requests.post", return_value=mock_resp):
        with caplog.at_level(logging.WARNING, logger="meo.tools.monthly_digest"):
            _send_to_slack("test")
    assert any("Monthly digest Slack send failed" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# run_monthly_digest
# ---------------------------------------------------------------------------

@pytest.fixture()
def _patch_history(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.monthly_digest.get_post_history",
        lambda key: list(_POST_HISTORY) if key == "the_body_kyoto" else [],
    )
    monkeypatch.setattr(
        "meo.tools.monthly_digest.get_reply_history",
        lambda key: list(_REPLY_HISTORY) if key == "the_body_kyoto" else [],
    )


def test_run_monthly_digest_dry_run_does_not_send_to_slack(_patch_history, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    with patch("meo.tools.monthly_digest._month_range", return_value=(_START, _END)):
        with patch("meo.tools.monthly_digest.requests.post") as mock_post:
            result = run_monthly_digest(dry_run=True)
    mock_post.assert_not_called()
    assert isinstance(result, str)
    assert len(result) > 0


def test_run_monthly_digest_live_sends_to_slack(_patch_history, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("meo.tools.monthly_digest._month_range", return_value=(_START, _END)):
        with patch("meo.tools.monthly_digest.requests.post", return_value=mock_resp) as mock_post:
            result = run_monthly_digest(dry_run=False)
    mock_post.assert_called_once()
    assert "月次サマリー" in result


def test_run_monthly_digest_filters_history_to_previous_month(_patch_history):
    with patch("meo.tools.monthly_digest._month_range", return_value=(_START, _END)):
        text = run_monthly_digest(dry_run=True)
    # Fixture has 5 in-window posts for the_body_kyoto and 0 for mybear → total 5
    assert "投稿 5件" in text


def test_run_monthly_digest_returns_string_with_month_label(_patch_history):
    with patch("meo.tools.monthly_digest._month_range", return_value=(_START, _END)):
        text = run_monthly_digest(dry_run=True)
    assert "2026年7月" in text


def test_run_monthly_digest_excludes_out_of_month_entries(_patch_history):
    # Verify entries from Jun 30 and Aug 1 are excluded
    with patch("meo.tools.monthly_digest._month_range", return_value=(_START, _END)):
        text = run_monthly_digest(dry_run=True)
    # mybear has 0 posts (no history); total should be 5, not 7
    assert "投稿 5件" in text  # 5 in-window entries for the_body_kyoto only


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def test_main_dry_run_prints_digest_to_stdout(_patch_history, capsys):
    with patch("meo.tools.monthly_digest._month_range", return_value=(_START, _END)):
        with patch("sys.argv", ["meo-monthly-digest", "--dry-run"]):
            main()
    captured = capsys.readouterr()
    assert "月次サマリー" in captured.out


def test_main_live_run_prints_and_sends(_patch_history, monkeypatch, capsys):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("meo.tools.monthly_digest._month_range", return_value=(_START, _END)):
        with patch("meo.tools.monthly_digest.requests.post", return_value=mock_resp) as mock_post:
            with patch("sys.argv", ["meo-monthly-digest"]):
                main()
    captured = capsys.readouterr()
    assert "月次サマリー" in captured.out
    mock_post.assert_called_once()


def test_main_dry_run_does_not_send(_patch_history, monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    with patch("meo.tools.monthly_digest._month_range", return_value=(_START, _END)):
        with patch("meo.tools.monthly_digest.requests.post") as mock_post:
            with patch("sys.argv", ["meo-monthly-digest", "--dry-run"]):
                main()
    mock_post.assert_not_called()
