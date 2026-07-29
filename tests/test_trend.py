"""Tests for meo.tools.trend — period-over-period trend comparison."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from meo.tools.trend import (
    _avg_stars,
    _filter_by_date,
    _format_delta_count,
    _format_delta_stars,
    _format_output,
    _monthly_ranges,
    _period_label,
    _star_value,
    _weekly_ranges,
    main,
    run_trend,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STORES = [
    {"key": "the_body_osaka_shinsaibashi", "name": "THE BODY 大阪 心斎橋店", "industry": "beauty_salon"},
    {"key": "the_body_kyoto", "name": "THE BODY 京都店", "industry": "beauty_salon"},
]

_TODAY_WEEKLY = date(2026, 7, 29)  # Wednesday; cur = 2026-07-22~28, prev = 2026-07-15~21
_TODAY_MONTHLY = date(2026, 7, 29)  # cur = June, prev = May

_POST_HISTORY_OSAKA = [
    {"date": "2026-07-22", "theme": "キャンペーン", "text": "post A"},
    {"date": "2026-07-25", "theme": "スタッフ紹介", "text": "post B"},
    {"date": "2026-07-28", "theme": "キャンペーン", "text": "post C"},
    # previous period
    {"date": "2026-07-15", "theme": "季節", "text": "post D"},
    {"date": "2026-07-20", "theme": "お知らせ", "text": "post E"},
    # outside both windows
    {"date": "2026-07-01", "theme": "古い", "text": "too old"},
]

_REPLY_HISTORY_OSAKA = [
    {"date": "2026-07-22", "reviewer": "田中", "stars": "FIVE", "reply": "ありがとう"},
    {"date": "2026-07-26", "reviewer": "鈴木", "stars": "FOUR", "reply": "またどうぞ"},
    # previous period
    {"date": "2026-07-16", "reviewer": "佐藤", "stars": "THREE", "reply": "承りました"},
    # outside both windows
    {"date": "2026-07-01", "reviewer": "古い", "stars": "ONE", "reply": "昔の返信"},
]


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.trend.cfg.store_list", lambda: list(_STORES))


# ---------------------------------------------------------------------------
# _weekly_ranges
# ---------------------------------------------------------------------------

def test_weekly_ranges_cur_end_is_yesterday():
    today = date(2026, 7, 29)
    cur_start, cur_end, _prev_start, _prev_end = _weekly_ranges(today)
    assert cur_end == date(2026, 7, 28)


def test_weekly_ranges_cur_window_is_7_days():
    today = date(2026, 7, 29)
    cur_start, cur_end, _prev_start, _prev_end = _weekly_ranges(today)
    assert (cur_end - cur_start).days == 6  # inclusive: 7 days


def test_weekly_ranges_cur_start():
    today = date(2026, 7, 29)
    cur_start, _cur_end, _prev_start, _prev_end = _weekly_ranges(today)
    assert cur_start == date(2026, 7, 22)


def test_weekly_ranges_prev_window_is_7_days():
    today = date(2026, 7, 29)
    _cur_start, _cur_end, prev_start, prev_end = _weekly_ranges(today)
    assert (prev_end - prev_start).days == 6


def test_weekly_ranges_no_overlap():
    today = date(2026, 7, 29)
    cur_start, _cur_end, _prev_start, prev_end = _weekly_ranges(today)
    assert prev_end < cur_start


def test_weekly_ranges_prev_end_is_day_before_cur_start():
    today = date(2026, 7, 29)
    cur_start, _cur_end, _prev_start, prev_end = _weekly_ranges(today)
    assert prev_end == cur_start - __import__("datetime").timedelta(days=1)


# ---------------------------------------------------------------------------
# _monthly_ranges
# ---------------------------------------------------------------------------

def test_monthly_ranges_cur_is_previous_calendar_month():
    today = date(2026, 7, 29)
    cur_start, cur_end, _prev_start, _prev_end = _monthly_ranges(today)
    assert cur_start == date(2026, 6, 1)
    assert cur_end == date(2026, 6, 30)


def test_monthly_ranges_prev_is_month_before_cur():
    today = date(2026, 7, 29)
    _cur_start, _cur_end, prev_start, prev_end = _monthly_ranges(today)
    assert prev_start == date(2026, 5, 1)
    assert prev_end == date(2026, 5, 31)


def test_monthly_ranges_january_wraps_to_december():
    today = date(2026, 1, 15)
    cur_start, cur_end, _prev_start, _prev_end = _monthly_ranges(today)
    assert cur_start == date(2025, 12, 1)
    assert cur_end == date(2025, 12, 31)


def test_monthly_ranges_january_prev_is_november():
    today = date(2026, 1, 15)
    _cur_start, _cur_end, prev_start, prev_end = _monthly_ranges(today)
    assert prev_start == date(2025, 11, 1)
    assert prev_end == date(2025, 11, 30)


def test_monthly_ranges_march_prev_includes_february():
    today = date(2026, 3, 1)
    _cur_start, _cur_end, prev_start, prev_end = _monthly_ranges(today)
    assert prev_start == date(2026, 1, 1)
    assert prev_end == date(2026, 1, 31)


# ---------------------------------------------------------------------------
# _star_value
# ---------------------------------------------------------------------------

def test_star_value_five():
    assert _star_value("FIVE") == 5


def test_star_value_one():
    assert _star_value("ONE") == 1


def test_star_value_three():
    assert _star_value("THREE") == 3


def test_star_value_unknown_returns_zero():
    assert _star_value("UNKNOWN") == 0


def test_star_value_empty_returns_zero():
    assert _star_value("") == 0


# ---------------------------------------------------------------------------
# _avg_stars
# ---------------------------------------------------------------------------

def test_avg_stars_empty_returns_none():
    assert _avg_stars([]) is None


def test_avg_stars_all_five():
    entries = [{"stars": "FIVE"}, {"stars": "FIVE"}]
    assert _avg_stars(entries) == 5.0


def test_avg_stars_mixed():
    entries = [{"stars": "FIVE"}, {"stars": "THREE"}]
    assert _avg_stars(entries) == 4.0


def test_avg_stars_unknown_entry_excluded():
    entries = [{"stars": "FIVE"}, {"stars": "UNKNOWN"}, {"stars": "ONE"}]
    assert _avg_stars(entries) == 3.0  # (5+1)/2


def test_avg_stars_no_valid_stars_returns_none():
    entries = [{"stars": ""}, {"reviewer": "田中"}]
    assert _avg_stars(entries) is None


# ---------------------------------------------------------------------------
# _format_delta_count
# ---------------------------------------------------------------------------

def test_format_delta_count_zero_returns_plus_minus():
    assert _format_delta_count(5, 5) == "±0"


def test_format_delta_count_positive_shows_percent():
    assert _format_delta_count(7, 5) == "+2 (+40%)"


def test_format_delta_count_negative_shows_percent():
    result = _format_delta_count(3, 6)
    assert result == "-3 (-50%)"


def test_format_delta_count_no_prev_no_percent():
    # prev=0 → no percentage (avoids division-by-zero / misleading "∞%")
    assert _format_delta_count(5, 0) == "+5"


def test_format_delta_count_both_zero():
    assert _format_delta_count(0, 0) == "±0"


# ---------------------------------------------------------------------------
# _format_delta_stars
# ---------------------------------------------------------------------------

def test_format_delta_stars_both_none():
    assert _format_delta_stars(None, None) == "—"


def test_format_delta_stars_cur_none():
    assert _format_delta_stars(None, 4.5) == "—"


def test_format_delta_stars_prev_none():
    assert _format_delta_stars(4.5, None) == "—"


def test_format_delta_stars_positive():
    assert _format_delta_stars(4.5, 4.2) == "+0.3"


def test_format_delta_stars_negative():
    assert _format_delta_stars(3.8, 4.5) == "-0.7"


def test_format_delta_stars_zero():
    assert _format_delta_stars(4.5, 4.5) == "±0.0"


# ---------------------------------------------------------------------------
# _period_label
# ---------------------------------------------------------------------------

def test_period_label_weekly():
    start = date(2026, 7, 22)
    end = date(2026, 7, 28)
    assert _period_label(start, end, "weekly") == "2026-07-22 〜 2026-07-28"


def test_period_label_monthly_july():
    start = date(2026, 7, 1)
    end = date(2026, 7, 31)
    assert _period_label(start, end, "monthly") == "2026年7月"


def test_period_label_monthly_december():
    start = date(2025, 12, 1)
    end = date(2025, 12, 31)
    assert _period_label(start, end, "monthly") == "2025年12月"


def test_period_label_monthly_january():
    start = date(2026, 1, 1)
    end = date(2026, 1, 31)
    assert _period_label(start, end, "monthly") == "2026年1月"


# ---------------------------------------------------------------------------
# _filter_by_date (inline — also tested indirectly via run_trend)
# ---------------------------------------------------------------------------

def test_filter_by_date_includes_boundary_dates():
    from meo.tools.trend import _filter_by_date
    entries = [
        {"date": "2026-07-22"},
        {"date": "2026-07-28"},
    ]
    result = _filter_by_date(entries, date(2026, 7, 22), date(2026, 7, 28))
    assert len(result) == 2


def test_filter_by_date_excludes_outside():
    from meo.tools.trend import _filter_by_date
    entries = [{"date": "2026-07-21"}, {"date": "2026-07-29"}]
    result = _filter_by_date(entries, date(2026, 7, 22), date(2026, 7, 28))
    assert result == []


def test_filter_by_date_skips_invalid_date():
    from meo.tools.trend import _filter_by_date
    entries = [{"date": "not-a-date"}, {"date": "2026-07-25"}]
    result = _filter_by_date(entries, date(2026, 7, 22), date(2026, 7, 28))
    assert len(result) == 1


# ---------------------------------------------------------------------------
# run_trend
# ---------------------------------------------------------------------------

@pytest.fixture
def _patch_history(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.trend.get_post_history",
        lambda key: _POST_HISTORY_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )
    monkeypatch.setattr(
        "meo.tools.trend.get_reply_history",
        lambda key: _REPLY_HISTORY_OSAKA if key == "the_body_osaka_shinsaibashi" else [],
    )


def test_run_trend_returns_expected_keys(_patch_history, monkeypatch):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(_TODAY_WEEKLY.year, _TODAY_WEEKLY.month, _TODAY_WEEKLY.day, tzinfo=tz))
    }))
    result = run_trend(period="weekly")
    for key in ("stores", "cur_start", "cur_end", "prev_start", "prev_end", "period"):
        assert key in result


def test_run_trend_weekly_period_label(_patch_history, monkeypatch):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    result = run_trend(period="weekly")
    assert result["period"] == "weekly"
    assert result["cur_end"] == date(2026, 7, 28)


def test_run_trend_monthly_period_label(_patch_history, monkeypatch):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    result = run_trend(period="monthly")
    assert result["period"] == "monthly"
    assert result["cur_start"] == date(2026, 6, 1)
    assert result["cur_end"] == date(2026, 6, 30)


def test_run_trend_filters_cur_period_posts(_patch_history, monkeypatch):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    result = run_trend(period="weekly")
    osaka = next(m for m in result["stores"] if m["store"]["key"] == "the_body_osaka_shinsaibashi")
    # 3 posts in 2026-07-22~28
    assert len(osaka["cur_posts"]) == 3


def test_run_trend_filters_prev_period_posts(_patch_history, monkeypatch):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    result = run_trend(period="weekly")
    osaka = next(m for m in result["stores"] if m["store"]["key"] == "the_body_osaka_shinsaibashi")
    # 2 posts in 2026-07-15~21
    assert len(osaka["prev_posts"]) == 2


def test_run_trend_cur_avg_stars_computed(_patch_history, monkeypatch):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    result = run_trend(period="weekly")
    osaka = next(m for m in result["stores"] if m["store"]["key"] == "the_body_osaka_shinsaibashi")
    # FIVE + FOUR in current period → avg 4.5
    assert osaka["cur_avg_stars"] == 4.5


def test_run_trend_prev_avg_stars_computed(_patch_history, monkeypatch):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    result = run_trend(period="weekly")
    osaka = next(m for m in result["stores"] if m["store"]["key"] == "the_body_osaka_shinsaibashi")
    # THREE in previous period → avg 3.0
    assert osaka["prev_avg_stars"] == 3.0


def test_run_trend_store_filter_limits_output(_patch_history, monkeypatch):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    result = run_trend(period="weekly", store_filter=["the_body_osaka_shinsaibashi"])
    assert len(result["stores"]) == 1
    assert result["stores"][0]["store"]["key"] == "the_body_osaka_shinsaibashi"


def test_run_trend_empty_history_gives_none_avg(_patch_history, monkeypatch):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    result = run_trend(period="weekly")
    kyoto = next(m for m in result["stores"] if m["store"]["key"] == "the_body_kyoto")
    assert kyoto["cur_avg_stars"] is None
    assert kyoto["prev_avg_stars"] is None


# ---------------------------------------------------------------------------
# _format_output
# ---------------------------------------------------------------------------

def _make_result(period="weekly", today=None):
    if today is None:
        today = date(2026, 7, 29)
    if period == "monthly":
        from meo.tools.trend import _monthly_ranges
        cur_start, cur_end, prev_start, prev_end = _monthly_ranges(today)
    else:
        from meo.tools.trend import _weekly_ranges
        cur_start, cur_end, prev_start, prev_end = _weekly_ranges(today)
    return {
        "period": period,
        "cur_start": cur_start,
        "cur_end": cur_end,
        "prev_start": prev_start,
        "prev_end": prev_end,
        "stores": [
            {
                "store": {"key": "the_body_kyoto", "name": "THE BODY 京都店"},
                "cur_posts": [{"date": "2026-07-22"}, {"date": "2026-07-25"}],
                "prev_posts": [{"date": "2026-07-15"}],
                "cur_replies": [{"date": "2026-07-23", "stars": "FIVE"}],
                "prev_replies": [{"date": "2026-07-16", "stars": "THREE"}, {"date": "2026-07-17", "stars": "THREE"}],
                "cur_avg_stars": 5.0,
                "prev_avg_stars": 3.0,
            },
        ],
    }


def test_format_output_contains_title():
    text = _format_output(_make_result())
    assert "トレンドレポート" in text


def test_format_output_weekly_shows_week_label():
    text = _format_output(_make_result(period="weekly"))
    assert "週次比較" in text


def test_format_output_monthly_shows_month_label():
    text = _format_output(_make_result(period="monthly"))
    assert "月次比較" in text


def test_format_output_contains_store_name():
    text = _format_output(_make_result())
    assert "THE BODY 京都店" in text


def test_format_output_contains_store_key():
    text = _format_output(_make_result())
    assert "the_body_kyoto" in text


def test_format_output_contains_cur_period_label():
    text = _format_output(_make_result(period="weekly"))
    assert "2026-07-22 〜 2026-07-28" in text


def test_format_output_monthly_contains_japanese_month():
    text = _format_output(_make_result(period="monthly"))
    assert "2026年6月" in text


def test_format_output_contains_arrow_delta():
    text = _format_output(_make_result())
    assert "→" in text


def test_format_output_contains_post_count():
    text = _format_output(_make_result())
    assert "2件" in text  # 2 cur posts


def test_format_output_contains_star_delta():
    text = _format_output(_make_result())
    # cur_avg=5.0, prev_avg=3.0 → +2.0
    assert "+2.0" in text


def test_format_output_contains_total_line():
    text = _format_output(_make_result())
    assert "合計" in text


def test_format_output_weekly_shows_今週():
    text = _format_output(_make_result(period="weekly"))
    assert "今週" in text


def test_format_output_monthly_shows_前月():
    text = _format_output(_make_result(period="monthly"))
    assert "前月" in text


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_default_period_weekly(_patch_history, monkeypatch, capsys):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    with patch("sys.argv", ["meo-trend"]):
        main()
    captured = capsys.readouterr()
    assert "週次比較" in captured.out


def test_main_period_monthly(_patch_history, monkeypatch, capsys):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    with patch("sys.argv", ["meo-trend", "--period", "monthly"]):
        main()
    captured = capsys.readouterr()
    assert "月次比較" in captured.out


def test_main_unknown_store_exits_1(_patch_history, monkeypatch):
    with patch("sys.argv", ["meo-trend", "--store", "unknown_store"]):
        with pytest.raises(SystemExit) as exc_info:
            main()
    assert exc_info.value.code == 1


def test_main_known_store_prints_output(_patch_history, monkeypatch, capsys):
    monkeypatch.setattr("meo.tools.trend.datetime", type("_DT", (), {
        "now": staticmethod(lambda tz=None: datetime(2026, 7, 29, tzinfo=tz))
    }))
    with patch("sys.argv", ["meo-trend", "--store", "the_body_osaka_shinsaibashi"]):
        main()
    captured = capsys.readouterr()
    assert "the_body_osaka_shinsaibashi" in captured.out
    assert "the_body_kyoto" not in captured.out
