"""Tests for meo.tools.score_history — daily health-grade trend table."""

from __future__ import annotations

import sys
from datetime import date
from unittest.mock import patch

import pytest

from meo.tools.score_history import (
    _date_range,
    _dates_in_range,
    _format_output,
    _store_short_name,
    main,
    run_score_history,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_STORES = [
    {
        "key": "the_body_osaka_shinsaibashi",
        "name": "THE BODY 大阪 心斎橋店",
        "industry": "beauty_salon",
        "location_id": "accounts/111/locations/222",
        "drive_folder_id": "folder_osaka",
    },
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
        "location_id": "accounts/333/locations/444",
        "drive_folder_id": "folder_kyoto",
    },
    {
        "key": "mybear_studio_kyoto",
        "name": "MYBEAR STUDIO 京都店",
        "industry": "fitness_studio",
        "location_id": "accounts/555/locations/666",
        "drive_folder_id": "TODO: Google Drive folder ID",
    },
]

_TODAY = date(2026, 8, 4)


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.score_history.cfg.store_list", lambda: list(_STORES))


@pytest.fixture()
def _no_snapshots(monkeypatch):
    monkeypatch.setattr("meo.tools.score_history.get_score_snapshots", lambda: [])


def _make_snapshots(entries: list[tuple[str, dict[str, str]]]) -> list[dict]:
    """Build a list of snapshot dicts from (date_str, grades) pairs."""
    return [{"date": d, "grades": g} for d, g in entries]


# ---------------------------------------------------------------------------
# _date_range
# ---------------------------------------------------------------------------

def test_date_range_end_is_yesterday():
    # today=2026-08-04 → yesterday=2026-08-03
    start, end = _date_range(7, date(2026, 8, 4))
    assert end == date(2026, 8, 3)


def test_date_range_start_is_correct_for_7_days():
    # today=2026-08-04, end=2026-08-03, 7-day window → start=2026-07-28
    start, end = _date_range(7, date(2026, 8, 4))
    assert start == date(2026, 7, 28)


def test_date_range_start_is_correct_for_14_days():
    # today=2026-08-04, end=2026-08-03, 14-day window → start=2026-07-21
    start, end = _date_range(14, date(2026, 8, 4))
    assert start == date(2026, 7, 21)


def test_date_range_1_day_start_equals_end():
    start, end = _date_range(1, date(2026, 8, 4))
    assert start == end == date(2026, 8, 3)


# ---------------------------------------------------------------------------
# _dates_in_range
# ---------------------------------------------------------------------------

def test_dates_in_range_newest_first():
    dates = _dates_in_range(date(2026, 7, 30), date(2026, 8, 1))
    assert dates[0] == date(2026, 8, 1)


def test_dates_in_range_count():
    dates = _dates_in_range(date(2026, 7, 28), date(2026, 8, 1))
    assert len(dates) == 5


def test_dates_in_range_single_day():
    dates = _dates_in_range(date(2026, 8, 1), date(2026, 8, 1))
    assert dates == [date(2026, 8, 1)]


def test_dates_in_range_covers_range():
    dates = _dates_in_range(date(2026, 7, 29), date(2026, 7, 31))
    assert date(2026, 7, 29) in dates
    assert date(2026, 7, 31) in dates


# ---------------------------------------------------------------------------
# _store_short_name
# ---------------------------------------------------------------------------

def test_store_short_name_short_name_unchanged():
    assert _store_short_name("THE BODY", 10) == "THE BODY"


def test_store_short_name_exactly_at_width():
    assert _store_short_name("1234567890", 10) == "1234567890"


def test_store_short_name_truncated():
    assert _store_short_name("THE BODY 大阪 心斎橋店", 10) == "THE BODY 大"


def test_store_short_name_default_width():
    name = "A" * 20
    result = _store_short_name(name)
    assert len(result) == 12


# ---------------------------------------------------------------------------
# run_score_history — structure
# ---------------------------------------------------------------------------

def test_run_score_history_returns_expected_keys(_no_snapshots):
    data = run_score_history(days=7, today=_TODAY)
    assert "days" in data
    assert "start" in data
    assert "end" in data
    assert "stores" in data
    assert "rows" in data
    assert "snapshot_count" in data


def test_run_score_history_days_value(_no_snapshots):
    data = run_score_history(days=7, today=_TODAY)
    assert data["days"] == 7


def test_run_score_history_end_is_yesterday(_no_snapshots):
    data = run_score_history(days=7, today=_TODAY)
    assert data["end"] == date(2026, 8, 3)


def test_run_score_history_start_is_correct(_no_snapshots):
    data = run_score_history(days=7, today=_TODAY)
    assert data["start"] == date(2026, 7, 28)


def test_run_score_history_stores_all_by_default(_no_snapshots):
    data = run_score_history(today=_TODAY)
    keys = [s["key"] for s in data["stores"]]
    assert "the_body_osaka_shinsaibashi" in keys
    assert "the_body_kyoto" in keys
    assert "mybear_studio_kyoto" in keys


def test_run_score_history_store_filter(_no_snapshots):
    data = run_score_history(store_filter=["the_body_kyoto"], today=_TODAY)
    assert len(data["stores"]) == 1
    assert data["stores"][0]["key"] == "the_body_kyoto"


def test_run_score_history_rows_count_equals_days(_no_snapshots):
    data = run_score_history(days=7, today=_TODAY)
    assert len(data["rows"]) == 7


def test_run_score_history_rows_newest_first(_no_snapshots):
    data = run_score_history(days=3, today=_TODAY)
    dates = [r["date"] for r in data["rows"]]
    assert dates == sorted(dates, reverse=True)


def test_run_score_history_snapshot_count_zero_when_no_data(_no_snapshots):
    data = run_score_history(today=_TODAY)
    assert data["snapshot_count"] == 0


# ---------------------------------------------------------------------------
# run_score_history — with data
# ---------------------------------------------------------------------------

def test_run_score_history_snapshot_in_range_included(monkeypatch):
    snaps = _make_snapshots([("2026-07-31", {"the_body_kyoto": "S"})])
    monkeypatch.setattr("meo.tools.score_history.get_score_snapshots", lambda: snaps)
    data = run_score_history(days=7, today=_TODAY)
    row_dates = [r["date"] for r in data["rows"]]
    assert "2026-07-31" in row_dates
    row = next(r for r in data["rows"] if r["date"] == "2026-07-31")
    assert row["grades"]["the_body_kyoto"] == "S"


def test_run_score_history_snapshot_outside_range_excluded(monkeypatch):
    # 2026-07-01 is outside a 7-day window ending 2026-08-03
    snaps = _make_snapshots([("2026-07-01", {"the_body_kyoto": "A"})])
    monkeypatch.setattr("meo.tools.score_history.get_score_snapshots", lambda: snaps)
    data = run_score_history(days=7, today=_TODAY)
    all_grades = [r["grades"] for r in data["rows"] if r["grades"]]
    assert all_grades == []


def test_run_score_history_snapshot_count_counts_non_empty_rows(monkeypatch):
    snaps = _make_snapshots([
        ("2026-08-03", {"the_body_kyoto": "A"}),
        ("2026-08-01", {"the_body_kyoto": "B"}),
    ])
    monkeypatch.setattr("meo.tools.score_history.get_score_snapshots", lambda: snaps)
    data = run_score_history(days=7, today=_TODAY)
    assert data["snapshot_count"] == 2


def test_run_score_history_days_without_snapshot_have_empty_grades(monkeypatch):
    snaps = _make_snapshots([("2026-08-03", {"the_body_kyoto": "A"})])
    monkeypatch.setattr("meo.tools.score_history.get_score_snapshots", lambda: snaps)
    data = run_score_history(days=7, today=_TODAY)
    empty_rows = [r for r in data["rows"] if not r["grades"]]
    assert len(empty_rows) == 6


def test_run_score_history_invalid_date_in_snapshot_skipped(monkeypatch):
    snaps = [{"date": "not-a-date", "grades": {"the_body_kyoto": "B"}}]
    monkeypatch.setattr("meo.tools.score_history.get_score_snapshots", lambda: snaps)
    data = run_score_history(days=7, today=_TODAY)
    assert data["snapshot_count"] == 0


def test_run_score_history_today_uses_jst_when_none(_no_snapshots):
    data = run_score_history(days=7, today=None)
    assert data["end"] is not None


def test_run_score_history_snapshot_today_excluded(monkeypatch):
    # A snapshot dated "today" should NOT appear in the window (today is excluded)
    snaps = _make_snapshots([(_TODAY.isoformat(), {"the_body_kyoto": "S"})])
    monkeypatch.setattr("meo.tools.score_history.get_score_snapshots", lambda: snaps)
    data = run_score_history(days=7, today=_TODAY)
    assert data["snapshot_count"] == 0


# ---------------------------------------------------------------------------
# _format_output
# ---------------------------------------------------------------------------

def _make_data(rows: list[dict], stores=None, days=7):
    if stores is None:
        stores = [{"key": "the_body_kyoto", "name": "THE BODY 京都店"}]
    return {
        "days": days,
        "start": date(2026, 7, 25),
        "end": date(2026, 7, 31),
        "stores": stores,
        "rows": rows,
        "snapshot_count": sum(1 for r in rows if r["grades"]),
    }


def test_format_output_contains_title():
    data = _make_data([])
    output = _format_output(data)
    assert "ヘルススコア履歴" in output


def test_format_output_contains_date_range():
    data = _make_data([])
    output = _format_output(data)
    assert "2026-07-25" in output
    assert "2026-07-31" in output


def test_format_output_contains_store_name():
    data = _make_data([])
    output = _format_output(data)
    assert "京都" in output


def test_format_output_contains_legend():
    data = _make_data([])
    output = _format_output(data)
    assert "凡例" in output


def test_format_output_shows_grade_letter_in_row(monkeypatch):
    # Use 2026-07-29 (not 2026-07-31 which appears in the header date range)
    rows = [
        {"date": "2026-07-29", "grades": {"the_body_kyoto": "S"}},
        {"date": "2026-07-28", "grades": {}},
    ]
    data = _make_data(rows)
    output = _format_output(data)
    lines = output.splitlines()
    row_line = next(l for l in lines if "2026-07-29" in l)
    assert "S" in row_line


def test_format_output_shows_missing_symbol_when_no_grade():
    rows = [{"date": "2026-07-28", "grades": {}}]
    data = _make_data(rows)
    output = _format_output(data)
    lines = output.splitlines()
    row_line = next(l for l in lines if "2026-07-28" in l)
    assert "—" in row_line


def test_format_output_snapshot_count_line():
    rows = [
        {"date": "2026-07-31", "grades": {"the_body_kyoto": "B"}},
        {"date": "2026-07-30", "grades": {}},
    ]
    data = _make_data(rows, days=7)
    data["snapshot_count"] = 1
    output = _format_output(data)
    assert "1/7" in output


def test_format_output_no_stores_shows_placeholder():
    data = {
        "days": 7, "start": date(2026, 7, 25), "end": date(2026, 7, 31),
        "stores": [], "rows": [], "snapshot_count": 0,
    }
    output = _format_output(data)
    assert "店舗データなし" in output


def test_format_output_multiple_stores_all_in_header():
    stores = [
        {"key": "the_body_osaka_shinsaibashi", "name": "THE BODY 大阪 心斎橋店"},
        {"key": "the_body_kyoto", "name": "THE BODY 京都店"},
    ]
    data = _make_data([], stores=stores)
    output = _format_output(data)
    assert "大阪" in output
    assert "京都" in output


def test_format_output_days_count_in_header():
    data = _make_data([], days=14)
    data["start"] = date(2026, 7, 18)
    output = _format_output(data)
    assert "14" in output


def test_format_output_grade_d_shown_as_d():
    # Use 2026-07-29 to avoid collision with end date 2026-07-31 in the header
    rows = [{"date": "2026-07-29", "grades": {"the_body_kyoto": "D"}}]
    data = _make_data(rows)
    output = _format_output(data)
    lines = output.splitlines()
    row_line = next(l for l in lines if "2026-07-29" in l)
    assert "D" in row_line


def test_format_output_all_grades_shown():
    stores = [
        {"key": "s1", "name": "Store1"},
        {"key": "s2", "name": "Store2"},
        {"key": "s3", "name": "Store3"},
        {"key": "s4", "name": "Store4"},
        {"key": "s5", "name": "Store5"},
    ]
    # Use 2026-07-28 to avoid collision with end=2026-07-31 in the header
    rows = [{"date": "2026-07-28", "grades": {
        "s1": "S", "s2": "A", "s3": "B", "s4": "C", "s5": "D"
    }}]
    data = {
        "days": 7, "start": date(2026, 7, 25), "end": date(2026, 7, 31),
        "stores": stores, "rows": rows, "snapshot_count": 1,
    }
    output = _format_output(data)
    row_line = next(l for l in output.splitlines() if "2026-07-28" in l)
    for g in ("S", "A", "B", "C", "D"):
        assert g in row_line


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_prints_output(_no_snapshots, capsys):
    sys.argv = ["meo-score-history"]
    main()
    out = capsys.readouterr().out
    assert "ヘルススコア履歴" in out


def test_main_default_days_is_14(_no_snapshots, capsys):
    sys.argv = ["meo-score-history"]
    main()
    out = capsys.readouterr().out
    assert "14" in out


def test_main_days_flag(_no_snapshots, capsys):
    sys.argv = ["meo-score-history", "--days", "7"]
    main()
    out = capsys.readouterr().out
    assert "7" in out


def test_main_invalid_days_exits_1(_no_snapshots):
    sys.argv = ["meo-score-history", "--days", "0"]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_days_above_max_exits_1(_no_snapshots):
    sys.argv = ["meo-score-history", "--days", "61"]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_unknown_store_exits_1(_no_snapshots):
    sys.argv = ["meo-score-history", "--store", "nonexistent_store"]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_store_filter_limits_columns(_no_snapshots, capsys):
    sys.argv = ["meo-score-history", "--store", "the_body_kyoto"]
    main()
    out = capsys.readouterr().out
    assert "京都" in out
    assert "大阪" not in out
    assert "MYBEAR" not in out


def test_main_output_file_written(_no_snapshots, tmp_path, capsys):
    out_file = tmp_path / "history.txt"
    sys.argv = ["meo-score-history", "--output", str(out_file)]
    main()
    assert out_file.exists()
    assert "ヘルススコア履歴" in out_file.read_text(encoding="utf-8")


def test_main_output_file_write_error_non_fatal(_no_snapshots, capsys):
    sys.argv = ["meo-score-history", "--output", "/nonexistent_dir/x.txt"]
    main()
    out = capsys.readouterr().out
    assert "ヘルススコア履歴" in out
