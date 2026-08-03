"""Tests for meo.tools.score — per-store health scorecard."""

from __future__ import annotations

import sys
from datetime import date
from unittest.mock import MagicMock, patch

import pytest
import requests

from meo.tools.score import (
    _action_items,
    _avg_stars_30_days,
    _drive_grade,
    _format_output,
    _grade_rank,
    _held_grade,
    _is_healthy,
    _posts_last_7_days,
    _posting_rate_grade,
    _send_score_to_slack,
    _star_grade,
    _worst_grade,
    main,
    run_score,
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
        "drive_folder_id": "folder_osaka_abc",
    },
    {
        "key": "the_body_kyoto",
        "name": "THE BODY 京都店",
        "industry": "beauty_salon",
        "location_id": "accounts/333/locations/444",
        "drive_folder_id": "folder_kyoto_xyz",
    },
    {
        "key": "mybear_studio_kyoto",
        "name": "MYBEAR STUDIO 京都店",
        "industry": "fitness_studio",
        "location_id": "accounts/555/locations/666",
        "drive_folder_id": "TODO: Google Drive folder ID",
    },
]

_TODAY = date(2026, 8, 2)  # Saturday — "today" for all tests
_YESTERDAY = date(2026, 8, 1)


@pytest.fixture(autouse=True)
def _patch_stores(monkeypatch):
    monkeypatch.setattr("meo.tools.score.cfg.store_list", lambda: list(_STORES))


@pytest.fixture()
def _no_state(monkeypatch):
    """Stub out all state accessors to return empty data."""
    monkeypatch.setattr("meo.tools.score.get_post_history", lambda key: [])
    monkeypatch.setattr("meo.tools.score.get_reply_history", lambda key: [])
    monkeypatch.setattr("meo.tools.score.get_held_reviews", lambda key: [])


# ---------------------------------------------------------------------------
# _grade_rank
# ---------------------------------------------------------------------------

def test_grade_rank_s_is_zero():
    assert _grade_rank("S") == 0


def test_grade_rank_d_is_four():
    assert _grade_rank("D") == 4


def test_grade_rank_unknown_grade_returns_4():
    assert _grade_rank("X") == 4


# ---------------------------------------------------------------------------
# _worst_grade
# ---------------------------------------------------------------------------

def test_worst_grade_empty_list_returns_D():
    assert _worst_grade([]) == "D"


def test_worst_grade_single_grade_returned():
    assert _worst_grade(["A"]) == "A"


def test_worst_grade_mixed_returns_worst():
    assert _worst_grade(["S", "C", "A"]) == "C"


def test_worst_grade_all_B_returns_B():
    assert _worst_grade(["B", "B", "B"]) == "B"


def test_worst_grade_D_dominates():
    assert _worst_grade(["S", "D", "A", "B"]) == "D"


# ---------------------------------------------------------------------------
# _is_healthy
# ---------------------------------------------------------------------------

def test_is_healthy_S_is_true():
    assert _is_healthy("S") is True


def test_is_healthy_A_is_true():
    assert _is_healthy("A") is True


def test_is_healthy_B_is_true():
    assert _is_healthy("B") is True


def test_is_healthy_C_is_false():
    assert _is_healthy("C") is False


def test_is_healthy_D_is_false():
    assert _is_healthy("D") is False


# ---------------------------------------------------------------------------
# _posting_rate_grade
# ---------------------------------------------------------------------------

def test_posting_rate_grade_7_returns_S():
    assert _posting_rate_grade(7) == "S"


def test_posting_rate_grade_8_returns_S():
    assert _posting_rate_grade(8) == "S"


def test_posting_rate_grade_6_returns_A():
    assert _posting_rate_grade(6) == "A"


def test_posting_rate_grade_5_returns_B():
    assert _posting_rate_grade(5) == "B"


def test_posting_rate_grade_4_returns_C():
    assert _posting_rate_grade(4) == "C"


def test_posting_rate_grade_3_returns_C():
    assert _posting_rate_grade(3) == "C"


def test_posting_rate_grade_2_returns_D():
    assert _posting_rate_grade(2) == "D"


def test_posting_rate_grade_0_returns_D():
    assert _posting_rate_grade(0) == "D"


# ---------------------------------------------------------------------------
# _held_grade
# ---------------------------------------------------------------------------

def test_held_grade_0_returns_S():
    assert _held_grade(0) == "S"


def test_held_grade_1_returns_A():
    assert _held_grade(1) == "A"


def test_held_grade_2_returns_B():
    assert _held_grade(2) == "B"


def test_held_grade_3_returns_C():
    assert _held_grade(3) == "C"


def test_held_grade_4_returns_C():
    assert _held_grade(4) == "C"


def test_held_grade_5_returns_D():
    assert _held_grade(5) == "D"


def test_held_grade_10_returns_D():
    assert _held_grade(10) == "D"


# ---------------------------------------------------------------------------
# _star_grade
# ---------------------------------------------------------------------------

def test_star_grade_none_returns_D():
    assert _star_grade(None) == "D"


def test_star_grade_5_point_0_returns_S():
    assert _star_grade(5.0) == "S"


def test_star_grade_4_point_8_returns_S():
    assert _star_grade(4.8) == "S"


def test_star_grade_4_point_7_returns_A():
    assert _star_grade(4.7) == "A"


def test_star_grade_4_point_5_returns_A():
    assert _star_grade(4.5) == "A"


def test_star_grade_4_point_0_returns_B():
    assert _star_grade(4.0) == "B"


def test_star_grade_3_point_5_returns_C():
    assert _star_grade(3.5) == "C"


def test_star_grade_3_point_4_returns_D():
    assert _star_grade(3.4) == "D"


def test_star_grade_1_point_0_returns_D():
    assert _star_grade(1.0) == "D"


# ---------------------------------------------------------------------------
# _drive_grade
# ---------------------------------------------------------------------------

def test_drive_grade_empty_string_returns_D():
    assert _drive_grade("") == "D"


def test_drive_grade_todo_placeholder_returns_D():
    assert _drive_grade("TODO: Google Drive folder ID") == "D"


def test_drive_grade_configured_id_returns_S():
    assert _drive_grade("folder_abc123") == "S"


# ---------------------------------------------------------------------------
# _posts_last_7_days
# ---------------------------------------------------------------------------

def test_posts_last_7_days_counts_within_window():
    history = [
        {"date": "2026-07-26", "text": "post"},
        {"date": "2026-07-31", "text": "post"},
    ]
    assert _posts_last_7_days(history, _TODAY) == 2


def test_posts_last_7_days_excludes_today():
    history = [{"date": "2026-08-02", "text": "post"}]
    assert _posts_last_7_days(history, _TODAY) == 0


def test_posts_last_7_days_excludes_before_window():
    history = [{"date": "2026-07-24", "text": "post"}]
    assert _posts_last_7_days(history, _TODAY) == 0


def test_posts_last_7_days_skips_invalid_date():
    history = [
        {"date": "not-a-date", "text": "bad"},
        {"date": "2026-07-31", "text": "ok"},
    ]
    assert _posts_last_7_days(history, _TODAY) == 1


# ---------------------------------------------------------------------------
# _avg_stars_30_days
# ---------------------------------------------------------------------------

def test_avg_stars_entries_in_window_averaged():
    history = [
        {"date": "2026-07-31", "stars": "FIVE"},
        {"date": "2026-07-30", "stars": "THREE"},
    ]
    result = _avg_stars_30_days(history, _TODAY)
    assert result == 4.0


def test_avg_stars_entries_outside_window_excluded():
    # 30-day window: 2026-07-02 to 2026-08-01
    history = [
        {"date": "2026-07-01", "stars": "ONE"},
        {"date": "2026-07-31", "stars": "FIVE"},
    ]
    result = _avg_stars_30_days(history, _TODAY)
    assert result == 5.0


def test_avg_stars_invalid_date_skipped():
    history = [
        {"date": "bad-date", "stars": "FIVE"},
        {"date": "2026-07-31", "stars": "FOUR"},
    ]
    result = _avg_stars_30_days(history, _TODAY)
    assert result == 4.0


def test_avg_stars_unknown_star_value_skipped():
    history = [
        {"date": "2026-07-31", "stars": "UNKNOWN"},
        {"date": "2026-07-30", "stars": "FIVE"},
    ]
    result = _avg_stars_30_days(history, _TODAY)
    assert result == 5.0


def test_avg_stars_no_valid_entries_returns_none():
    history = [{"date": "2026-07-31", "stars": "MYSTERY"}]
    result = _avg_stars_30_days(history, _TODAY)
    assert result is None


def test_avg_stars_empty_history_returns_none():
    assert _avg_stars_30_days([], _TODAY) is None


# ---------------------------------------------------------------------------
# _action_items
# ---------------------------------------------------------------------------

def test_action_items_all_healthy_returns_empty():
    items = _action_items(
        held_count=0,
        posts_7d=7,
        avg_stars=4.8,
        held_grade="S",
        post_grade="S",
        star_grade="S",
        drive_grade_val="S",
    )
    assert items == []


def test_action_items_unhealthy_held_grade_adds_manual_reply_action():
    items = _action_items(
        held_count=3,
        posts_7d=7,
        avg_stars=4.8,
        held_grade="C",
        post_grade="S",
        star_grade="S",
        drive_grade_val="S",
    )
    assert any("手動返信待ち" in item for item in items)
    assert any("3件" in item for item in items)


def test_action_items_healthy_held_grade_with_count_adds_mild_action():
    items = _action_items(
        held_count=1,
        posts_7d=7,
        avg_stars=4.8,
        held_grade="A",
        post_grade="S",
        star_grade="S",
        drive_grade_val="S",
    )
    assert any("保留中" in item for item in items)
    assert not any("手動返信待ち" in item for item in items)


def test_action_items_zero_held_no_held_action():
    items = _action_items(
        held_count=0,
        posts_7d=7,
        avg_stars=4.8,
        held_grade="S",
        post_grade="S",
        star_grade="S",
        drive_grade_val="S",
    )
    assert not any("レビュー" in item for item in items)


def test_action_items_drive_grade_D_adds_drive_action():
    items = _action_items(
        held_count=0,
        posts_7d=7,
        avg_stars=4.8,
        held_grade="S",
        post_grade="S",
        star_grade="S",
        drive_grade_val="D",
    )
    assert any("Drive フォルダ未設定" in item for item in items)


def test_action_items_unhealthy_post_grade_adds_posting_action():
    items = _action_items(
        held_count=0,
        posts_7d=3,
        avg_stars=4.8,
        held_grade="S",
        post_grade="C",
        star_grade="S",
        drive_grade_val="S",
    )
    assert any("投稿頻度低下" in item for item in items)
    assert any("3/7" in item for item in items)


def test_action_items_unhealthy_star_with_avg_adds_star_action():
    items = _action_items(
        held_count=0,
        posts_7d=7,
        avg_stars=3.5,
        held_grade="S",
        post_grade="S",
        star_grade="C",
        drive_grade_val="S",
    )
    assert any("★3.5" in item for item in items)


def test_action_items_unhealthy_star_no_data_adds_data_none_action():
    items = _action_items(
        held_count=0,
        posts_7d=7,
        avg_stars=None,
        held_grade="S",
        post_grade="S",
        star_grade="D",
        drive_grade_val="S",
    )
    assert any("返信評価データなし" in item for item in items)


# ---------------------------------------------------------------------------
# run_score
# ---------------------------------------------------------------------------

def test_run_score_returns_all_stores(_no_state):
    results = run_score(today=_TODAY)
    assert len(results) == 3


def test_run_score_store_filter_applies(_no_state):
    results = run_score(store_filter=["the_body_kyoto"], today=_TODAY)
    assert len(results) == 1
    assert results[0]["key"] == "the_body_kyoto"


def test_run_score_result_has_expected_keys(_no_state):
    results = run_score(today=_TODAY)
    r = results[0]
    for key in ("key", "name", "posts_7d", "avg_stars", "held_count",
                "folder_id", "post_grade", "held_grade", "star_grade",
                "drive_grade", "overall", "healthy", "actions"):
        assert key in r, f"Missing key: {key}"


def test_run_score_overall_is_worst_dimension(monkeypatch):
    monkeypatch.setattr("meo.tools.score.get_post_history", lambda key: [])
    monkeypatch.setattr("meo.tools.score.get_reply_history", lambda key: [])
    monkeypatch.setattr(
        "meo.tools.score.get_held_reviews",
        lambda key: [{"review_id": "r1"}] * 5,
    )
    results = run_score(store_filter=["the_body_kyoto"], today=_TODAY)
    r = results[0]
    assert r["held_grade"] == "D"
    assert r["overall"] == "D"


def test_run_score_healthy_flag_true_when_posting_and_configured(monkeypatch):
    history_7 = [{"date": f"2026-07-{d:02d}", "text": "p"} for d in range(26, 33)]
    reply_hist = [{"date": "2026-07-31", "stars": "FIVE"}]
    monkeypatch.setattr("meo.tools.score.get_post_history", lambda key: history_7)
    monkeypatch.setattr("meo.tools.score.get_reply_history", lambda key: reply_hist)
    monkeypatch.setattr("meo.tools.score.get_held_reviews", lambda key: [])
    results = run_score(store_filter=["the_body_kyoto"], today=_TODAY)
    assert results[0]["healthy"] is True


def test_run_score_healthy_flag_false_for_unconfigured_drive(_no_state):
    results = run_score(store_filter=["mybear_studio_kyoto"], today=_TODAY)
    assert results[0]["drive_grade"] == "D"
    assert results[0]["healthy"] is False


def test_run_score_avg_stars_none_when_no_reply_history(_no_state):
    results = run_score(store_filter=["the_body_kyoto"], today=_TODAY)
    assert results[0]["avg_stars"] is None


def test_run_score_today_none_uses_jst_today(_no_state, monkeypatch):
    """When today is omitted, run_score uses the current JST date internally."""
    monkeypatch.setattr(
        "meo.tools.score.datetime",
        type("FakeDT", (), {
            "now": staticmethod(lambda tz=None: __import__("datetime").datetime(
                2026, 8, 2, 9, 0, 0, tzinfo=tz
            ))
        }),
    )
    results = run_score(store_filter=["the_body_kyoto"])
    assert len(results) == 1  # ran without error; date derived from mock


# ---------------------------------------------------------------------------
# _format_output
# ---------------------------------------------------------------------------

def _make_result(
    key="the_body_kyoto",
    name="THE BODY 京都店",
    posts_7d=7,
    avg_stars=4.8,
    held_count=0,
    folder_id="folder_xyz",
    post_grade="S",
    held_grade="S",
    star_grade="S",
    drive_grade="S",
    overall="S",
    healthy=True,
    actions=None,
):
    return {
        "key": key,
        "name": name,
        "posts_7d": posts_7d,
        "avg_stars": avg_stars,
        "held_count": held_count,
        "folder_id": folder_id,
        "post_grade": post_grade,
        "held_grade": held_grade,
        "star_grade": star_grade,
        "drive_grade": drive_grade,
        "overall": overall,
        "healthy": healthy,
        "actions": actions or [],
    }


def test_format_output_has_title():
    out = _format_output([_make_result()], _TODAY)
    assert "MEO Automation — 店舗別ヘルススコア" in out


def test_format_output_has_date():
    out = _format_output([_make_result()], _TODAY)
    assert "2026-08-02" in out


def test_format_output_has_store_name():
    out = _format_output([_make_result()], _TODAY)
    assert "THE BODY 京都店" in out


def test_format_output_has_store_key():
    out = _format_output([_make_result()], _TODAY)
    assert "the_body_kyoto" in out


def test_format_output_overall_grade_shown():
    out = _format_output([_make_result(overall="A")], _TODAY)
    assert "総合:" in out
    assert "A" in out


def test_format_output_posts_7d_shown():
    out = _format_output([_make_result(posts_7d=5)], _TODAY)
    assert "5/7" in out


def test_format_output_held_count_shown():
    out = _format_output([_make_result(held_count=2)], _TODAY)
    assert "2件" in out


def test_format_output_avg_stars_shown():
    out = _format_output([_make_result(avg_stars=4.5)], _TODAY)
    assert "★4.5" in out


def test_format_output_no_data_stars_shows_label():
    out = _format_output([_make_result(avg_stars=None)], _TODAY)
    assert "データなし" in out


def test_format_output_actions_listed():
    r = _make_result(actions=["Drive フォルダ未設定 — 対応が必要です"])
    out = _format_output([r], _TODAY)
    assert "▶ アクション:" in out
    assert "Drive フォルダ未設定" in out


def test_format_output_no_results_shows_placeholder():
    out = _format_output([], _TODAY)
    assert "店舗データなし" in out


def test_format_output_all_healthy_shows_checkmark():
    out = _format_output([_make_result(healthy=True)], _TODAY)
    assert "✅" in out
    assert "全店舗" in out


def test_format_output_some_unhealthy_shows_warning():
    r1 = _make_result(healthy=True)
    r2 = _make_result(
        key="mybear_studio_kyoto",
        name="MYBEAR STUDIO 京都店",
        healthy=False,
        overall="D",
    )
    out = _format_output([r1, r2], _TODAY)
    assert "⚠️" in out
    assert "MYBEAR STUDIO 京都店" in out


def test_format_output_no_actions_no_action_section():
    out = _format_output([_make_result(actions=[])], _TODAY)
    assert "▶ アクション:" not in out


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------

def test_main_exits_0_when_all_healthy(_no_state, monkeypatch, capsys):
    # Stub all stores to fully configured (replace mybear's TODO folder)
    configured_stores = [
        {**s, "drive_folder_id": "folder_configured"}
        for s in _STORES
    ]
    monkeypatch.setattr("meo.tools.score.cfg.store_list", lambda: configured_stores)
    history_7 = [{"date": f"2026-07-{d:02d}", "text": "p"} for d in range(26, 33)]
    reply_hist = [{"date": "2026-07-31", "stars": "FIVE"}]
    monkeypatch.setattr("meo.tools.score.get_post_history", lambda key: history_7)
    monkeypatch.setattr("meo.tools.score.get_reply_history", lambda key: reply_hist)
    sys.argv = ["meo-score"]
    main()  # should not raise
    out = capsys.readouterr().out
    assert "MEO Automation" in out


def test_main_exits_1_when_store_unhealthy(_no_state, monkeypatch):
    sys.argv = ["meo-score"]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_unknown_store_exits_1(_no_state, capsys):
    sys.argv = ["meo-score", "--store", "no_such_store"]
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "Unknown" in capsys.readouterr().err


def test_main_store_filter_limits_output(_no_state, capsys):
    sys.argv = ["meo-score", "--store", "the_body_kyoto"]
    with pytest.raises(SystemExit):
        main()
    out = capsys.readouterr().out
    assert "THE BODY 京都店" in out
    assert "心斎橋" not in out


def test_main_prints_scorecard(_no_state, capsys):
    sys.argv = ["meo-score"]
    with pytest.raises(SystemExit):
        main()
    out = capsys.readouterr().out
    assert "ヘルススコア" in out


# ---------------------------------------------------------------------------
# _send_score_to_slack
# ---------------------------------------------------------------------------

def test_send_score_to_slack_no_webhook_url_returns_false(monkeypatch):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    assert _send_score_to_slack("scorecard text") is False


def test_send_score_to_slack_success_returns_true(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.return_value = None
    with patch("requests.post", return_value=mock_resp):
        result = _send_score_to_slack("scorecard text")
    assert result is True


def test_send_score_to_slack_http_error_returns_false(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    mock_resp = MagicMock()
    mock_resp.raise_for_status.side_effect = requests.HTTPError("500")
    with patch("requests.post", return_value=mock_resp):
        result = _send_score_to_slack("scorecard text")
    assert result is False


def test_send_score_to_slack_network_error_returns_false(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/test")
    with patch("requests.post", side_effect=Exception("connection timeout")):
        result = _send_score_to_slack("scorecard text")
    assert result is False


# ---------------------------------------------------------------------------
# main() — --slack flag
# ---------------------------------------------------------------------------

def test_main_slack_flag_calls_send_score(_no_state):
    sys.argv = ["meo-score", "--slack"]
    with patch("meo.tools.score._send_score_to_slack") as mock_send:
        with pytest.raises(SystemExit):
            main()
    mock_send.assert_called_once()


def test_main_no_slack_flag_does_not_call_send_score(_no_state):
    sys.argv = ["meo-score"]
    with patch("meo.tools.score._send_score_to_slack") as mock_send:
        with pytest.raises(SystemExit):
            main()
    mock_send.assert_not_called()


def test_main_slack_passes_formatted_scorecard(_no_state):
    sys.argv = ["meo-score", "--slack"]
    with patch("meo.tools.score._send_score_to_slack") as mock_send:
        with pytest.raises(SystemExit):
            main()
    sent_text = mock_send.call_args[0][0]
    assert "ヘルススコア" in sent_text
