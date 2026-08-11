"""Tests for meo/tools/insights.py — Google, LLM, and auth are all mocked."""

from __future__ import annotations

import json
import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from meo.tools.insights import (
    _fmt_delta,
    _format_output,
    _sum_period,
    run_insights,
)


# ---------------------------------------------------------------------------
# Fixtures & helpers
# ---------------------------------------------------------------------------

_STORES = [
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "location_id": "accounts/1/locations/42",
        "drive_folder_id": "folder_abc",
        "industry": "beauty_salon",
    },
    {
        "key": "mybear_studio_kyoto",
        "name": "MYBEAR STUDIO 京都店",
        "location_id": "TODO_location_id",
        "drive_folder_id": "folder_xyz",
        "industry": "beauty_salon",
    },
]

_METRICS_RETURN: dict[str, dict[str, int]] = {
    "BUSINESS_IMPRESSIONS_DESKTOP_MAPS":   {"2026-07-26": 100, "2026-07-27": 110,
                                            "2026-08-02": 120, "2026-08-03": 130},
    "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": {"2026-07-26": 200, "2026-07-27": 210,
                                            "2026-08-02": 220, "2026-08-03": 230},
    "BUSINESS_IMPRESSIONS_MOBILE_MAPS":    {"2026-07-26": 50,  "2026-08-02": 60},
    "BUSINESS_IMPRESSIONS_MOBILE_SEARCH":  {"2026-07-26": 80,  "2026-08-02": 90},
    "BUSINESS_DIRECTION_REQUESTS":         {"2026-07-26": 10,  "2026-08-02": 12},
    "CALL_CLICKS":                         {"2026-07-26": 5,   "2026-08-02": 7},
    "WEBSITE_CLICKS":                      {"2026-07-26": 30,  "2026-08-02": 35},
}

_TODAY = date(2026, 8, 11)


def _mock_client(return_value=None):
    """Return a MagicMock PerformanceClient whose fetch_daily_metrics returns return_value."""
    client = MagicMock()
    client.fetch_daily_metrics.return_value = return_value if return_value is not None else {}
    return client


# ---------------------------------------------------------------------------
# _sum_period
# ---------------------------------------------------------------------------

def test_sum_period_sums_within_range():
    dated = {"2026-08-01": 10, "2026-08-02": 20, "2026-08-03": 30}
    assert _sum_period(dated, date(2026, 8, 1), date(2026, 8, 2)) == 30


def test_sum_period_excludes_outside_range():
    dated = {"2026-07-31": 999, "2026-08-01": 5, "2026-08-15": 888}
    assert _sum_period(dated, date(2026, 8, 1), date(2026, 8, 10)) == 5


def test_sum_period_inclusive_boundaries():
    dated = {"2026-08-01": 1, "2026-08-07": 1}
    assert _sum_period(dated, date(2026, 8, 1), date(2026, 8, 7)) == 2


def test_sum_period_empty_dict():
    assert _sum_period({}, date(2026, 8, 1), date(2026, 8, 7)) == 0


def test_sum_period_invalid_date_key_skipped():
    dated = {"not-a-date": 100, "2026-08-01": 5}
    assert _sum_period(dated, date(2026, 8, 1), date(2026, 8, 7)) == 5


# ---------------------------------------------------------------------------
# _fmt_delta
# ---------------------------------------------------------------------------

def test_fmt_delta_positive():
    assert _fmt_delta(120, 100) == "+20%"


def test_fmt_delta_negative():
    assert _fmt_delta(80, 100) == "-20%"


def test_fmt_delta_zero():
    assert _fmt_delta(100, 100) == "±0%"


def test_fmt_delta_both_zero():
    assert _fmt_delta(0, 0) == "—"


def test_fmt_delta_from_zero_baseline():
    # prev=0, cur>0: avoid ∞%; return absolute delta
    result = _fmt_delta(5, 0)
    assert result == "+5"


def test_fmt_delta_rounds_percentage():
    # 10/33 ≈ 30%
    assert _fmt_delta(43, 33) == "+30%"


# ---------------------------------------------------------------------------
# run_insights — skipped stores
# ---------------------------------------------------------------------------

def test_run_insights_skips_todo_location(monkeypatch):
    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: [_STORES[1]])
    with patch("meo.tools.insights.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.insights.PerformanceClient", return_value=_mock_client()):
        results = run_insights(days=14)
    assert len(results) == 1
    assert results[0]["skipped"] is True
    assert results[0]["error"] is None
    assert results[0]["metrics_cur"] == {}


def test_run_insights_skips_empty_location(monkeypatch):
    store = {**_STORES[0], "location_id": ""}
    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: [store])
    with patch("meo.tools.insights.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.insights.PerformanceClient", return_value=_mock_client()):
        results = run_insights(days=14)
    assert results[0]["skipped"] is True


# ---------------------------------------------------------------------------
# run_insights — successful fetch
# ---------------------------------------------------------------------------

def test_run_insights_returns_metric_sums(monkeypatch):
    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: [_STORES[0]])
    with patch("meo.tools.insights.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.insights.PerformanceClient",
               return_value=_mock_client(_METRICS_RETURN)):
        with patch("meo.tools.insights.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = _TODAY
            results = run_insights(days=14)
    assert len(results) == 1
    r = results[0]
    assert r["skipped"] is False
    assert r["error"] is None
    # Website clicks: some in cur period, some in prev period
    assert "WEBSITE_CLICKS" in r["metrics_cur"]
    assert "WEBSITE_CLICKS" in r["metrics_prev"]


def test_run_insights_store_filter(monkeypatch):
    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: _STORES)
    with patch("meo.tools.insights.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.insights.PerformanceClient",
               return_value=_mock_client(_METRICS_RETURN)):
        results = run_insights(store_filter=["the_body_kyoto"], days=14)
    assert len(results) == 1
    assert results[0]["key"] == "the_body_kyoto"


def test_run_insights_all_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: _STORES)
    with patch("meo.tools.insights.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.insights.PerformanceClient",
               return_value=_mock_client(_METRICS_RETURN)):
        results = run_insights(days=14)
    assert len(results) == 2


def test_run_insights_error_captured(monkeypatch):
    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: [_STORES[0]])
    err_client = MagicMock()
    err_client.fetch_daily_metrics.side_effect = RuntimeError("403 Forbidden")
    with patch("meo.tools.insights.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.insights.PerformanceClient", return_value=err_client):
        results = run_insights(days=14)
    assert results[0]["error"] == "403 Forbidden"
    assert results[0]["skipped"] is False


def test_run_insights_date_boundaries_correct(monkeypatch):
    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: [_STORES[0]])
    with patch("meo.tools.insights.get_credentials", return_value=MagicMock()), \
         patch("meo.tools.insights.PerformanceClient",
               return_value=_mock_client({})) as mock_pc:
        mock_client_inst = mock_pc.return_value
        with patch("meo.tools.insights.datetime") as mock_dt:
            mock_dt.now.return_value.date.return_value = date(2026, 8, 11)
            results = run_insights(days=28)

    # days=28, half=14: cur_end=2026-08-10, cur_start=2026-07-28
    r = results[0]
    assert r["cur_end"] == date(2026, 8, 10)
    assert r["cur_start"] == date(2026, 7, 28)
    assert r["prev_end"] == date(2026, 7, 27)
    assert r["prev_start"] == date(2026, 7, 14)


# ---------------------------------------------------------------------------
# _format_output
# ---------------------------------------------------------------------------

def _make_result(
    *,
    skipped: bool = False,
    error: str | None = None,
    metrics_cur: dict | None = None,
    metrics_prev: dict | None = None,
) -> dict:
    return {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "location_id": "accounts/1/locations/42",
        "skipped": skipped,
        "error": error,
        "cur_start": date(2026, 7, 28),
        "cur_end": date(2026, 8, 10),
        "prev_start": date(2026, 7, 14),
        "prev_end": date(2026, 7, 27),
        "metrics_cur": metrics_cur or {},
        "metrics_prev": metrics_prev or {},
    }


def test_format_output_contains_store_name():
    result = _make_result(metrics_cur={"WEBSITE_CLICKS": 10}, metrics_prev={"WEBSITE_CLICKS": 8})
    output = _format_output([result], days=28, today=date(2026, 8, 11))
    assert "THE BODY 京都店" in output


def test_format_output_skipped_store_shows_placeholder():
    result = _make_result(skipped=True)
    output = _format_output([result], days=28, today=date(2026, 8, 11))
    assert "location_id" in output
    assert "PROGRESS.md" in output


def test_format_output_error_shows_message():
    result = _make_result(error="403 PERMISSION_DENIED")
    output = _format_output([result], days=28, today=date(2026, 8, 11))
    assert "403 PERMISSION_DENIED" in output
    assert "APIエラー" in output


def test_format_output_long_error_truncated():
    long_err = "x" * 200
    result = _make_result(error=long_err)
    output = _format_output([result], days=28, today=date(2026, 8, 11))
    assert "x" * 120 in output
    assert "x" * 150 not in output


def test_format_output_contains_period_lines():
    result = _make_result(metrics_cur={"WEBSITE_CLICKS": 5}, metrics_prev={"WEBSITE_CLICKS": 4})
    output = _format_output([result], days=28, today=date(2026, 8, 11))
    assert "当期" in output
    assert "前期" in output
    assert "14 日" in output


def test_format_output_impressions_group_shown():
    metrics = {
        "BUSINESS_IMPRESSIONS_DESKTOP_MAPS": 500,
        "BUSINESS_IMPRESSIONS_DESKTOP_SEARCH": 1000,
        "BUSINESS_IMPRESSIONS_MOBILE_MAPS": 300,
        "BUSINESS_IMPRESSIONS_MOBILE_SEARCH": 700,
    }
    result = _make_result(metrics_cur=metrics, metrics_prev={m: v - 100 for m, v in metrics.items()})
    output = _format_output([result], days=28, today=date(2026, 8, 11))
    assert "表示回数 合計" in output
    assert "PC マップ表示" in output


def test_format_output_action_metrics_shown():
    metrics = {
        "BUSINESS_DIRECTION_REQUESTS": 20,
        "CALL_CLICKS": 8,
        "WEBSITE_CLICKS": 45,
    }
    result = _make_result(metrics_cur=metrics, metrics_prev={m: max(v - 5, 0) for m, v in metrics.items()})
    output = _format_output([result], days=28, today=date(2026, 8, 11))
    assert "ルート案内" in output
    assert "電話クリック" in output
    assert "ウェブサイトクリック" in output


def test_format_output_empty_results():
    output = _format_output([], days=28, today=date(2026, 8, 11))
    assert "パフォーマンス分析" in output
    assert "─" in output


def test_format_output_contains_today_date():
    result = _make_result()
    output = _format_output([result], days=28, today=date(2026, 8, 11))
    assert "2026-08-11" in output


def test_format_output_multiple_stores():
    r1 = _make_result()
    r2 = {**_make_result(), "key": "the_body_osaka_shinsaibashi", "name": "THE BODY 大阪 心斎橋店"}
    output = _format_output([r1, r2], days=28, today=date(2026, 8, 11))
    assert "THE BODY 京都店" in output
    assert "THE BODY 大阪 心斎橋店" in output


# ---------------------------------------------------------------------------
# main() — CLI entrypoint
# ---------------------------------------------------------------------------

def _run_main(argv, results, monkeypatch):
    """Patch run_insights and run main() with argv, returning SystemExit code."""
    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: _STORES)
    with patch("meo.tools.insights.run_insights", return_value=results), \
         patch("meo.tools.insights.datetime") as mock_dt, \
         patch("sys.argv", argv):
        mock_dt.now.return_value.date.return_value = date(2026, 8, 11)
        try:
            from meo.tools.insights import main
            main()
            return 0
        except SystemExit as exc:
            return exc.code


def test_main_exit_0_all_clean(monkeypatch, capsys):
    results = [_make_result(metrics_cur={"WEBSITE_CLICKS": 5}, metrics_prev={"WEBSITE_CLICKS": 4})]
    code = _run_main(["meo-insights"], results, monkeypatch)
    assert code == 0


def test_main_exit_1_on_api_error(monkeypatch, capsys):
    results = [_make_result(error="403 Forbidden")]
    code = _run_main(["meo-insights"], results, monkeypatch)
    assert code == 1


def test_main_exit_0_when_all_skipped(monkeypatch, capsys):
    results = [_make_result(skipped=True)]
    code = _run_main(["meo-insights"], results, monkeypatch)
    assert code == 0


def test_main_json_output_valid(monkeypatch, capsys):
    results = [_make_result(metrics_cur={"WEBSITE_CLICKS": 5}, metrics_prev={"WEBSITE_CLICKS": 4})]
    code = _run_main(["meo-insights", "--json"], results, monkeypatch)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert isinstance(parsed, list)
    assert parsed[0]["key"] == "the_body_kyoto"
    assert isinstance(parsed[0]["cur_start"], str)  # dates serialised as strings


def test_main_json_dates_are_iso_strings(monkeypatch, capsys):
    results = [_make_result()]
    _run_main(["meo-insights", "--json"], results, monkeypatch)
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    for field in ("cur_start", "cur_end", "prev_start", "prev_end"):
        assert isinstance(parsed[0][field], str)
        date.fromisoformat(parsed[0][field])  # must parse without error


def test_main_unknown_store_exits_1(monkeypatch):
    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: _STORES)
    with patch("sys.argv", ["meo-insights", "--store", "nonexistent_store"]):
        try:
            from meo.tools.insights import main
            main()
        except SystemExit as exc:
            assert exc.code == 1


def test_main_days_too_small_exits_1(monkeypatch):
    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: _STORES)
    with patch("sys.argv", ["meo-insights", "--days", "1"]):
        try:
            from meo.tools.insights import main
            main()
        except SystemExit as exc:
            assert exc.code == 1


def test_main_store_filter_passed_to_run(monkeypatch, capsys):
    calls = []

    def fake_run(store_filter=None, days=28):
        calls.append({"store_filter": store_filter, "days": days})
        return [_make_result()]

    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: _STORES)
    with patch("meo.tools.insights.run_insights", side_effect=fake_run), \
         patch("meo.tools.insights.datetime") as mock_dt, \
         patch("sys.argv", ["meo-insights", "--store", "the_body_kyoto"]):
        mock_dt.now.return_value.date.return_value = date(2026, 8, 11)
        try:
            from meo.tools.insights import main
            main()
        except SystemExit:
            pass

    assert calls[0]["store_filter"] == ["the_body_kyoto"]


def test_main_days_flag_passed_to_run(monkeypatch, capsys):
    calls = []

    def fake_run(store_filter=None, days=28):
        calls.append({"store_filter": store_filter, "days": days})
        return [_make_result()]

    monkeypatch.setattr("meo.tools.insights.cfg.store_list", lambda: _STORES)
    with patch("meo.tools.insights.run_insights", side_effect=fake_run), \
         patch("meo.tools.insights.datetime") as mock_dt, \
         patch("sys.argv", ["meo-insights", "--days", "14"]):
        mock_dt.now.return_value.date.return_value = date(2026, 8, 11)
        try:
            from meo.tools.insights import main
            main()
        except SystemExit:
            pass

    assert calls[0]["days"] == 14
