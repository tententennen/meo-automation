"""Tests for meo.tools.calendar — posting calendar per store."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from io import StringIO
from unittest.mock import patch, mock_open

import pytest

from meo.tools.calendar import (
    _date_range,
    _gap_lines,
    _posted_dates,
    _symbols_row,
    _week_chunks,
    _week_header,
    _format_output,
    run_calendar,
    main,
    _POSTED,
    _NOT_POSTED,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_STORES = [
    {
        "key": "the_body_osaka_shinsaibashi",
        "name": "THE BODY 大阪 心斎橋店",
        "industry": "beauty_salon",
        "location_id": "accounts/111/locations/222",
        "drive_folder_id": "folder_abc",
    },
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
        "location_id": "accounts/333/locations/444",
        "drive_folder_id": "folder_xyz",
    },
    {
        "key": "mybear_studio_kyoto",
        "name": "MYBEAR STUDIO 京都店",
        "industry": "fitness_studio",
        "location_id": "accounts/555/locations/666",
        "drive_folder_id": "folder_mb",
    },
]

_TODAY = date(2026, 8, 1)   # Friday
_YESTERDAY = date(2026, 7, 31)


def _fake_now(tz=None):
    """Simulate datetime.now() returning 2026-08-01 (JST midnight = 2026-07-31 15:00 UTC)."""
    from zoneinfo import ZoneInfo
    jst = ZoneInfo("Asia/Tokyo")
    dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=jst)
    if tz is not None:
        return dt.astimezone(tz)
    return dt


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.calendar.cfg.store_list", lambda: list(_STORES))


@pytest.fixture(autouse=True)
def _patch_datetime(monkeypatch):
    monkeypatch.setattr("meo.tools.calendar.datetime", type(
        "FakeDT", (), {"now": staticmethod(_fake_now)}
    ))


# ---------------------------------------------------------------------------
# _date_range
# ---------------------------------------------------------------------------

def test_date_range_end_is_yesterday():
    _, end = _date_range(days=1)
    assert end == _YESTERDAY


def test_date_range_start_for_30_days():
    start, end = _date_range(days=30)
    assert (end - start).days == 29


def test_date_range_start_for_7_days():
    start, _ = _date_range(days=7)
    assert start == date(2026, 7, 25)


def test_date_range_start_for_1_day():
    start, end = _date_range(days=1)
    assert start == end == _YESTERDAY


# ---------------------------------------------------------------------------
# _posted_dates
# ---------------------------------------------------------------------------

_POST_HISTORY_DATA = [
    {"date": "2026-07-29", "theme": "A", "text": "post 1"},
    {"date": "2026-07-30", "theme": "B", "text": "post 2"},
    {"date": "2026-07-31", "theme": "C", "text": "post 3"},
    {"date": "2026-07-28", "theme": "D", "text": "post 4"},  # just outside 3-day window
]

_WIN_START = date(2026, 7, 29)
_WIN_END = date(2026, 7, 31)


def test_posted_dates_returns_dates_within_window(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.calendar.get_post_history",
        lambda key: _POST_HISTORY_DATA,
    )
    result = _posted_dates("any_key", _WIN_START, _WIN_END)
    assert result == {date(2026, 7, 29), date(2026, 7, 30), date(2026, 7, 31)}


def test_posted_dates_excludes_out_of_range(monkeypatch):
    monkeypatch.setattr(
        "meo.tools.calendar.get_post_history",
        lambda key: _POST_HISTORY_DATA,
    )
    result = _posted_dates("any_key", _WIN_START, _WIN_END)
    assert date(2026, 7, 28) not in result


def test_posted_dates_skips_invalid_date(monkeypatch):
    bad_history = [
        {"date": "not-a-date", "theme": "X", "text": "bad"},
        {"date": "2026-07-30", "theme": "Y", "text": "ok"},
    ]
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: bad_history)
    result = _posted_dates("any_key", _WIN_START, _WIN_END)
    assert result == {date(2026, 7, 30)}


def test_posted_dates_empty_history(monkeypatch):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    result = _posted_dates("any_key", _WIN_START, _WIN_END)
    assert result == set()


def test_posted_dates_duplicate_dates_deduplicated(monkeypatch):
    dup_history = [
        {"date": "2026-07-30", "theme": "A", "text": "x"},
        {"date": "2026-07-30", "theme": "B", "text": "y"},
    ]
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: dup_history)
    result = _posted_dates("any_key", _WIN_START, _WIN_END)
    assert result == {date(2026, 7, 30)}


# ---------------------------------------------------------------------------
# _week_chunks
# ---------------------------------------------------------------------------

def test_week_chunks_exactly_7():
    dates = [date(2026, 7, i) for i in range(1, 8)]
    chunks = _week_chunks(dates)
    assert len(chunks) == 1
    assert chunks[0] == dates


def test_week_chunks_14_gives_two_chunks():
    dates = [date(2026, 7, 1) + __import__("datetime").timedelta(days=i) for i in range(14)]
    chunks = _week_chunks(dates)
    assert len(chunks) == 2
    assert len(chunks[0]) == 7
    assert len(chunks[1]) == 7


def test_week_chunks_8_gives_two_chunks_last_partial():
    dates = [date(2026, 7, 1) + __import__("datetime").timedelta(days=i) for i in range(8)]
    chunks = _week_chunks(dates)
    assert len(chunks) == 2
    assert len(chunks[0]) == 7
    assert len(chunks[1]) == 1


def test_week_chunks_empty():
    assert _week_chunks([]) == []


# ---------------------------------------------------------------------------
# _symbols_row
# ---------------------------------------------------------------------------

def test_symbols_row_all_posted():
    dates = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]
    chunks = [dates]
    posted = set(dates)
    assert _symbols_row(chunks, posted) == f"{_POSTED}{_POSTED}{_POSTED}"


def test_symbols_row_none_posted():
    dates = [date(2026, 7, 1), date(2026, 7, 2)]
    chunks = [dates]
    assert _symbols_row(chunks, set()) == f"{_NOT_POSTED}{_NOT_POSTED}"


def test_symbols_row_mixed_posted():
    dates = [date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)]
    chunks = [dates]
    posted = {date(2026, 7, 1), date(2026, 7, 3)}
    assert _symbols_row(chunks, posted) == f"{_POSTED}{_NOT_POSTED}{_POSTED}"


def test_symbols_row_multiple_chunks_separated_by_space():
    dates1 = [date(2026, 7, i) for i in range(1, 8)]
    dates2 = [date(2026, 7, 8)]
    chunks = [dates1, dates2]
    posted = set(dates1 + dates2)
    result = _symbols_row(chunks, posted)
    assert " " in result  # groups separated
    parts = result.split(" ")
    assert len(parts) == 2
    assert parts[0] == _POSTED * 7
    assert parts[1] == _POSTED


# ---------------------------------------------------------------------------
# _week_header
# ---------------------------------------------------------------------------

def test_week_header_single_chunk():
    dates = [date(2026, 7, i) for i in range(1, 8)]
    chunks = [dates]
    hdr = _week_header(chunks)
    assert hdr.startswith("7/01")


def test_week_header_two_chunks_separated_by_space():
    from datetime import timedelta
    d = date(2026, 7, 1)
    dates1 = [d + timedelta(days=i) for i in range(7)]
    dates2 = [d + timedelta(days=7)]
    chunks = [dates1, dates2]
    hdr = _week_header(chunks)
    assert "7/01" in hdr
    assert "7/08" in hdr
    parts = hdr.split(" ")
    assert len(parts) >= 2  # at least two parts after split


def test_week_header_label_padded_to_chunk_width():
    from datetime import timedelta
    d = date(2026, 7, 1)
    dates = [d + timedelta(days=i) for i in range(7)]
    chunks = [dates]
    hdr = _week_header(chunks)
    # Label "7/01" is 4 chars; padded to 7 (chunk length)
    assert len(hdr) == 7


def test_week_header_partial_last_chunk():
    from datetime import timedelta
    d = date(2026, 7, 1)
    full = [d + timedelta(days=i) for i in range(7)]
    partial = [d + timedelta(days=7), d + timedelta(days=8)]  # 2 days
    chunks = [full, partial]
    hdr = _week_header(chunks)
    # Last chunk label should be present
    assert "7/08" in hdr


def test_week_header_skips_empty_chunk():
    # Defensive guard: an empty chunk in the list should be silently skipped.
    dates = [date(2026, 7, 1)]
    hdr = _week_header([[], dates])
    assert "7/01" in hdr


# ---------------------------------------------------------------------------
# _gap_lines
# ---------------------------------------------------------------------------

def test_gap_lines_no_gaps():
    dates = [date(2026, 7, 29), date(2026, 7, 30)]
    store_data = [
        {"store": {"key": "s1"}, "posted_dates": set(dates)},
    ]
    assert _gap_lines(store_data, dates) == []


def test_gap_lines_one_gap():
    dates = [date(2026, 7, 29), date(2026, 7, 30)]
    store_data = [
        {"store": {"key": "s1"}, "posted_dates": {date(2026, 7, 29)}},
    ]
    lines = _gap_lines(store_data, dates)
    assert len(lines) == 1
    assert "2026-07-30" in lines[0]
    assert "s1" in lines[0]


def test_gap_lines_multiple_stores_same_day():
    dates = [date(2026, 7, 29)]
    store_data = [
        {"store": {"key": "s1"}, "posted_dates": set()},
        {"store": {"key": "s2"}, "posted_dates": set()},
    ]
    lines = _gap_lines(store_data, dates)
    assert len(lines) == 2
    keys = [l.split("(")[1].rstrip(")") for l in lines]
    assert "s1" in keys
    assert "s2" in keys


def test_gap_lines_ordered_chronologically():
    dates = [date(2026, 7, 29), date(2026, 7, 30), date(2026, 7, 31)]
    store_data = [
        {"store": {"key": "s1"}, "posted_dates": {date(2026, 7, 30)}},
    ]
    lines = _gap_lines(store_data, dates)
    assert "2026-07-29" in lines[0]
    assert "2026-07-31" in lines[1]


# ---------------------------------------------------------------------------
# run_calendar
# ---------------------------------------------------------------------------

def test_run_calendar_returns_all_stores_by_default(monkeypatch):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    result = run_calendar(days=7)
    assert len(result["store_data"]) == 3


def test_run_calendar_store_filter(monkeypatch):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    result = run_calendar(days=7, store_keys=["the_body_kyoto"])
    assert len(result["store_data"]) == 1
    assert result["store_data"][0]["store"]["key"] == "the_body_kyoto"


def test_run_calendar_unknown_store_key_raises(monkeypatch):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    with pytest.raises(ValueError, match="Unknown store key"):
        run_calendar(days=7, store_keys=["nonexistent_store"])


def test_run_calendar_count_correct(monkeypatch):
    def fake_history(key):
        if key == "the_body_kyoto":
            return [{"date": "2026-07-31", "theme": "A", "text": "x"}]
        return []

    monkeypatch.setattr("meo.tools.calendar.get_post_history", fake_history)
    result = run_calendar(days=7, store_keys=["the_body_kyoto"])
    sd = result["store_data"][0]
    assert sd["count"] == 1
    assert sd["total"] == 7


def test_run_calendar_empty_history_gives_zero_count(monkeypatch):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    result = run_calendar(days=7)
    for sd in result["store_data"]:
        assert sd["count"] == 0


def test_run_calendar_start_end_dates(monkeypatch):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    result = run_calendar(days=7)
    assert result["end"] == _YESTERDAY
    assert (result["end"] - result["start"]).days == 6


# ---------------------------------------------------------------------------
# _format_output
# ---------------------------------------------------------------------------

def _make_data(days=7, counts=None):
    """Build synthetic run_calendar result for format tests."""
    from datetime import timedelta
    end = date(2026, 7, 31)
    start = end - timedelta(days=days - 1)
    dates = [start + timedelta(days=i) for i in range(days)]

    store_data = []
    for i, store in enumerate(_STORES):
        count = (counts or [0, 0, 0])[i] if counts else 0
        posted = set(dates[:count])
        store_data.append(
            {
                "store": store,
                "posted_dates": posted,
                "count": count,
                "total": days,
            }
        )
    return {"start": start, "end": end, "store_data": store_data}


def test_format_output_contains_title():
    text = _format_output(_make_data())
    assert "MEO Automation" in text
    assert "投稿カレンダー" in text


def test_format_output_contains_date_range():
    text = _format_output(_make_data(days=7))
    assert "2026-07-25" in text
    assert "2026-07-31" in text


def test_format_output_contains_store_names():
    text = _format_output(_make_data())
    assert "THE BODY 大阪 心斎橋店" in text
    assert "THE BODY 京都店" in text
    assert "MYBEAR STUDIO 京都店" in text


def test_format_output_posted_symbol_present_when_posted():
    data = _make_data(days=7, counts=[7, 0, 0])
    text = _format_output(data)
    # First store should have posted symbols
    assert _POSTED in text


def test_format_output_not_posted_symbol_present_when_missing():
    data = _make_data(days=7, counts=[0, 0, 0])
    text = _format_output(data)
    assert _NOT_POSTED in text


def test_format_output_rate_shown():
    data = _make_data(days=7, counts=[5, 7, 0])
    text = _format_output(data)
    assert "5/7" in text
    assert "7/7" in text
    assert "0/7" in text


def test_format_output_total_line():
    data = _make_data(days=7, counts=[7, 7, 7])
    text = _format_output(data)
    assert "全店舗合計" in text
    assert "21/21" in text


def test_format_output_no_gap_section_when_fully_posted():
    data = _make_data(days=7, counts=[7, 7, 7])
    text = _format_output(data)
    assert "投稿なしの日" not in text


def test_format_output_gap_section_when_gaps_exist():
    data = _make_data(days=7, counts=[6, 7, 7])  # first store missing one day
    text = _format_output(data)
    assert "投稿なしの日" in text
    assert "the_body_osaka_shinsaibashi" in text


def test_format_output_legend_present():
    text = _format_output(_make_data())
    assert "凡例" in text
    assert _POSTED in text
    assert _NOT_POSTED in text


def test_format_output_week_header_present():
    data = _make_data(days=14)
    text = _format_output(data)
    # Week header contains the first date of each 7-day chunk
    # start = 2026-07-18 → "7/18" and "7/25" for second chunk
    assert "7/18" in text or "7/25" in text


def test_format_output_100_percent_rate():
    data = _make_data(days=7, counts=[7, 7, 7])
    text = _format_output(data)
    assert "100%" in text


def test_format_output_0_percent_rate():
    data = _make_data(days=7, counts=[0, 0, 0])
    text = _format_output(data)
    assert "0%" in text


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_prints_output(monkeypatch, capsys):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    sys.argv = ["meo-calendar"]
    main()
    out = capsys.readouterr().out
    assert "MEO Automation" in out
    assert "投稿カレンダー" in out


def test_main_unknown_store_exits_1(monkeypatch, capsys):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    sys.argv = ["meo-calendar", "--store", "no_such_store"]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "Error" in capsys.readouterr().err


def test_main_store_filter(monkeypatch, capsys):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    sys.argv = ["meo-calendar", "--store", "the_body_kyoto"]
    main()
    out = capsys.readouterr().out
    assert "THE BODY 京都店" in out
    assert "THE BODY 大阪 心斎橋店" not in out


def test_main_days_flag(monkeypatch, capsys):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    sys.argv = ["meo-calendar", "--days", "7"]
    main()
    out = capsys.readouterr().out
    assert "直近7日" in out


def test_main_invalid_days_exits_1(monkeypatch, capsys):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    sys.argv = ["meo-calendar", "--days", "31"]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_output_file_written(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    out_file = tmp_path / "calendar.txt"
    sys.argv = ["meo-calendar", "--output", str(out_file)]
    main()
    assert out_file.exists()
    content = out_file.read_text(encoding="utf-8")
    assert "MEO Automation" in content


def test_main_output_file_write_error_does_not_crash(monkeypatch, capsys):
    monkeypatch.setattr("meo.tools.calendar.get_post_history", lambda key: [])
    sys.argv = ["meo-calendar", "--output", "/nonexistent_dir/calendar.txt"]
    # Should not raise — OSError is caught and printed as a warning
    main()
    err = capsys.readouterr().err
    assert "Warning" in err or "could not write" in err
